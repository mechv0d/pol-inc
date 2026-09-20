from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from pol_inc.application.packs import PackService
from pol_inc.application.sessions import SessionManager
from pol_inc.domain.errors import PackError, PolIncError
from pol_inc.domain.session import Party

from .formatting import esc, format_pack_list, format_session

logger = logging.getLogger(__name__)

router = Router(name="commands")

GROUP_TYPES = {"group", "supergroup"}


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "<b>POL Inc.</b> — политическая игра.\n"
        "Групповые команды: /newgame, /join, /leavegame, /game, /ss pack <id>\n"
        "Личные команды: /reg Название | Слоган | Идеология"
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

    await message.answer("\n".join(lines))


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
async def leavegame(message: Message, session_manager: SessionManager) -> None:
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
    else:
        await message.answer("Вы покинули сессию.")


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