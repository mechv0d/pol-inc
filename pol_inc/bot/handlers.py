from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from pol_inc.application.packs import PackService
from pol_inc.application.sessions import SessionManager
from pol_inc.domain.errors import PackError, PolIncError
from pol_inc.domain.session import Party

from .formatting import (
    esc,
    format_final,
    format_pack_list,
    format_resolution,
    format_session,
    format_turn,
    format_welcome,
)

logger = logging.getLogger(__name__)

router = Router(name="commands")

GROUP_TYPES = {"group", "supergroup"}
MESSAGE_CHUNK_LIMIT = 4000


def _chunk_lines(lines: list[str], limit: int = MESSAGE_CHUNK_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(line) <= limit:
            current = line
            continue

        for index in range(0, len(line), limit):
            chunks.append(line[index:index + limit])

        current = ""

    if current:
        chunks.append(current)

    return chunks


async def send_lines(bot: Bot, chat_id: int, lines: list[str]) -> None:
    for chunk in _chunk_lines(lines):
        await bot.send_message(chat_id=chat_id, text=chunk)


async def send_turn(
    bot: Bot,
    chat_id: int,
    session,
    pack_service: PackService,
) -> None:
    pack = session.pack

    if pack is None:
        return

    try:
        event = session.get_current_event(pack)
    except PolIncError as exc:
        logger.exception("Не удалось получить текущее событие")
        await bot.send_message(chat_id=chat_id, text=f"Не удалось получить событие: {esc(exc)}")
        return

    banner_url = pack_service.image_url(event.banner)

    if banner_url:
        try:
            await bot.send_photo(chat_id=chat_id, photo=banner_url)
        except Exception:
            logger.exception("Не удалось отправить баннер события")

    await send_lines(bot, chat_id, format_turn(session, pack, event))


async def send_resolution(
    bot: Bot,
    chat_id: int,
    session,
    resolution,
    pack_service: PackService,
) -> None:
    banner_url = pack_service.image_url(resolution.outcome.banner)

    if banner_url:
        try:
            await bot.send_photo(chat_id=chat_id, photo=banner_url)
        except Exception:
            logger.exception("Не удалось отправить баннер исхода")

    await send_lines(bot, chat_id, format_resolution(session, resolution))


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "<b>POL Inc.</b> — политическая игра.\n"
        "Групповые команды: /newgame, /join, /leavegame, /game, /ss pack <id>, /startgame\n"
        "Личные команды: /reg Название | Слоган | Идеология, /vote <номер>"
    )


@router.message(Command("game"))
async def game(
    message: Message,
    session_manager: SessionManager,
    pack_service: PackService,
) -> None:
    lines = ["<b>POL Inc.</b>"]

    session = None

    if message.chat.type in GROUP_TYPES:
        session = session_manager.get_by_chat(message.chat.id)
    elif message.from_user is not None:
        session = session_manager.get_by_user(message.from_user.id)

    if session:
        lines.append("")
        lines.extend(format_session(session))
    elif message.chat.type in GROUP_TYPES:
        lines.append("В этом чате нет сессии. Создать: /newgame")
    else:
        lines.append("Вы не участвуете в сессии.")

    try:
        metas = await pack_service.list_metas()
    except PackError as exc:
        lines.append("")
        lines.append(f"Список паков недоступен: {esc(exc)}")
    else:
        lines.append("")
        lines.extend(format_pack_list(metas))

    await send_lines(message.bot, message.chat.id, lines)


@router.message(Command("newgame"))
async def newgame(message: Message, session_manager: SessionManager) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Игра создаётся в групповом чате.")
        return

    if message.from_user is None:
        return

    try:
        session = await session_manager.create(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось создать сессию: {esc(exc)}")
        return

    await message.answer(
        "\n".join(
            [
                f"Сессия <code>{esc(session.code)}</code> создана.",
                "Присоединиться: /join <код>",
                "Посмотреть состояние: /game",
            ]
        )
    )


@router.message(Command("join"))
async def join(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Присоединяться к игре нужно в групповом чате.")
        return

    if not command.args:
        await message.answer("Использование: /join <код>")
        return

    if message.from_user is None:
        return

    code = command.args.strip().upper()

    try:
        result = await session_manager.join(
            code=code,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось присоединиться: {esc(exc)}")
        return

    if result.already_joined:
        await message.answer("Вы уже в этой сессии.")
        return

    await message.answer(
        f"Игрок присоединился к сессии <code>{esc(result.session.code)}</code>."
    )


@router.message(Command("leavegame"))
async def leavegame(
    message: Message,
    session_manager: SessionManager,
    pack_service: PackService,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return

    try:
        result = await session_manager.leave(message.from_user.id)
    except PolIncError as exc:
        await message.answer(f"Не удалось выйти из сессии: {esc(exc)}")
        return

    if result.closed:
        if result.closed_by_creator:
            await message.answer(
                f"Сессия <code>{esc(result.code)}</code> закрыта создателем."
            )
        else:
            await message.answer(
                f"Сессия <code>{esc(result.code)}</code> закрыта, потому что вышел последний игрок."
            )
    elif result.eliminated:
        await message.answer(
            "Вы покинули активную игру. Ваша партия продолжает ходить автоматически."
        )
    else:
        await message.answer("Вы покинули сессию.")

    if result.resolution is not None and result.session is not None:
        await send_resolution(
            bot,
            message.chat.id,
            result.session,
            result.resolution,
            pack_service,
        )

        if result.resolution.game_finished:
            await send_lines(bot, message.chat.id, format_final(result.session))
        else:
            await send_turn(bot, message.chat.id, result.session, pack_service)


@router.message(Command("closegame"))
async def closegame(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
) -> None:
    if message.from_user is None:
        return

    code = command.args.strip().upper() if command.args else None

    if not code:
        session = session_manager.get_by_chat(message.chat.id)
        if session:
            code = session.code

    if not code:
        await message.answer("Использование: /closegame <код>")
        return

    try:
        session = await session_manager.close(code=code, requester_id=message.from_user.id)
    except PolIncError as exc:
        await message.answer(f"Не удалось закрыть сессию: {esc(exc)}")
        return

    await message.answer(f"Сессия <code>{esc(session.code)}</code> закрыта.")


@router.message(Command("ss"))
async def ss(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
    pack_service: PackService,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Настройки сессии доступны в групповом чате.")
        return

    if message.from_user is None:
        return

    if not command.args:
        await message.answer("Использование: /ss pack <id>")
        return

    parts = command.args.strip().split()

    if len(parts) < 2 or parts[0].lower() != "pack":
        await message.answer("Пока поддерживается только: /ss pack <id>")
        return

    pack_id = parts[1].strip()

    try:
        meta = await pack_service.get_meta(pack_id)
        pack = await pack_service.load_pack(meta)
        session = await session_manager.set_pack(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            meta=meta,
            pack=pack,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось применить настройку: {esc(exc)}")
        return

    await message.answer(
        f"Пак {esc(meta.name)} установлен. Ходов: {session.duration}."
    )


@router.message(Command("reg"))
async def reg(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
) -> None:
    if message.chat.type in GROUP_TYPES:
        await message.answer("Регистрация партии происходит в личных сообщениях бота.")
        return

    if message.from_user is None:
        return

    if not command.args:
        await message.answer("Использование: /reg Название | Слоган | Идеология")
        return

    parts = [part.strip() for part in command.args.split("|")]

    if len(parts) != 3:
        await message.answer(
            "Нужно передать 3 части через '|': /reg Название | Слоган | Идеология"
        )
        return

    try:
        party = Party.create(name=parts[0], slogan=parts[1], ideology=parts[2])
        session = await session_manager.register_party(
            user_id=message.from_user.id,
            party=party,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось зарегистрировать партию: {esc(exc)}")
        return

    await message.answer(
        f"Партия «{esc(party.name)}» зарегистрирована в сессии <code>{esc(session.code)}</code>."
    )


@router.message(Command("startgame"))
async def startgame(
    message: Message,
    session_manager: SessionManager,
    pack_service: PackService,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Игра запускается в групповом чате.")
        return

    if message.from_user is None:
        return

    try:
        session = await session_manager.start_game(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось запустить игру: {esc(exc)}")
        return

    await send_lines(bot, message.chat.id, format_welcome(session))
    await send_turn(bot, message.chat.id, session, pack_service)


@router.message(Command("vote"))
async def vote(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
    pack_service: PackService,
    bot: Bot,
) -> None:
    if message.chat.type in GROUP_TYPES:
        await message.answer("Голосование проходит только в личных сообщениях бота.")
        return

    if message.from_user is None:
        return

    if not command.args:
        await message.answer("Использование: /vote <номер>")
        return

    try:
        session, changed, resolution = await session_manager.register_vote(
            user_id=message.from_user.id,
            choice=command.args,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось проголосовать: {esc(exc)}")
        return

    if changed:
        await message.answer("Голос принят.")
    else:
        await message.answer("Ваш голос за эту фракцию уже был учтен.")

    if resolution is None:
        return

    await send_resolution(
        bot,
        session.chat_id,
        session,
        resolution,
        pack_service,
    )

    if resolution.game_finished:
        await send_lines(bot, session.chat_id, format_final(session))
    else:
        await send_turn(bot, session.chat_id, session, pack_service)