from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from pol_inc.application.packs import PackService
from pol_inc.application.parties import PartyRepository
from pol_inc.application.sessions import SessionManager
from pol_inc.config import Settings
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.errors import PackError, PolIncError
from pol_inc.domain.session import Party

from .formatting import (
    esc,
    format_final,
    format_lobby,
    format_pack_list,
    format_party_card,
    format_resolution,
    format_session,
    format_turn,
    format_welcome,
)

logger = logging.getLogger(__name__)

router = Router(name="commands")

GROUP_TYPES = {"group", "supergroup"}
MESSAGE_CHUNK_LIMIT = 4000


class RegStates(StatesGroup):
    name = State()
    slogan = State()
    ideology = State()
    line = State()
    photo = State()


SKIP_PHOTO_CALLBACK = "reg:skip_photo"
PARTY_CAPTION_LIMIT = 1024


def _skip_photo_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=SKIP_PHOTO_CALLBACK)]
        ]
    )


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


async def send_or_update_lobby(
    bot: Bot,
    session_manager: SessionManager,
    session,
    *,
    repost_if_unchanged: bool = False,
) -> None:
    if session.status != SessionStatus.NEW:
        return

    text = "\n".join(format_lobby(session))

    if len(text) > 4096:
        text = text[:4000] + "\n..."

    if session.lobby_message_id:
        try:
            await bot.edit_message_text(
                chat_id=session.chat_id,
                message_id=session.lobby_message_id,
                text=text,
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                if not repost_if_unchanged:
                    return

                try:
                    await bot.delete_message(
                        chat_id=session.chat_id,
                        message_id=session.lobby_message_id,
                    )
                except Exception:
                    logger.debug("Не удалось удалить старое сообщение лобби.")
                    return
            else:
                logger.warning("Не удалось отредактировать сообщение лобби: %s", exc)
        except Exception:
            logger.exception("Ошибка при редактировании сообщения лобби")

    message = await bot.send_message(chat_id=session.chat_id, text=text)
    await session_manager.set_lobby_message_id(session.chat_id, message.message_id)


async def send_info_banner(
    bot: Bot,
    chat_id: int,
    pack_service: PackService,
) -> int | None:
    url = pack_service.image_url("game_info.jpg")

    if not url:
        await bot.send_message(chat_id=chat_id, text="📢 <b>Текущее событие</b>")
        return None

    try:
        message = await bot.send_photo(chat_id=chat_id, photo=url, has_spoiler=True)
        return message.message_id
    except Exception:
        logger.debug("Не удалось отправить game_info.jpg. Возможно, файла нет в бакете.")
        await bot.send_message(chat_id=chat_id, text="📢 <b>Текущее событие</b>")
        return None


async def send_reg_banner(
    bot: Bot,
    chat_id: int,
    pack_service: PackService,
) -> int | None:
    url = pack_service.image_url("game_reg.jpg")

    if not url:
        await bot.send_message(chat_id=chat_id, text="📋 <b>Регистрация партии</b>")
        return None

    try:
        message = await bot.send_photo(chat_id=chat_id, photo=url, has_spoiler=True)
        return message.message_id
    except Exception:
        logger.debug("Не удалось отправить game_reg.jpg. Возможно, файла нет в бакете.")
        await bot.send_message(chat_id=chat_id, text="📋 <b>Регистрация партии</b>")
        return None


async def try_set_default_pack(
    session_manager: SessionManager,
    pack_service: PackService,
    settings: Settings,
    session,
):
    if not settings.default_pack_id:
        return session

    try:
        meta = await pack_service.get_meta(settings.default_pack_id)
        pack = await pack_service.load_pack(meta)

        return await session_manager.set_pack(
            chat_id=session.chat_id,
            user_id=session.creator_id,
            meta=meta,
            pack=pack,
        )
    except PolIncError as exc:
        logger.warning("Не удалось установить пак по умолчанию: %s", exc)
        return session


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
        "Групповые команды: /newgame, /join, /leavegame, /game, /ss, /startgame\n"
        "Личные команды: /reg, /vote номер, /cancel"
    )


@router.message(Command("game"))
async def game(
    message: Message,
    session_manager: SessionManager,
    pack_service: PackService,
    bot: Bot,
) -> None:
    if message.chat.type in GROUP_TYPES:
        session = session_manager.get_by_chat(message.chat.id)

        if session is not None:
            if session.status == SessionStatus.NEW:
                if session.info_banner_message_id is None:
                    banner_id = await send_info_banner(bot, message.chat.id, pack_service)

                    if banner_id is not None:
                        await session_manager.set_info_banner_message_id(
                            message.chat.id,
                            banner_id,
                        )

                await send_or_update_lobby(
                    bot, session_manager, session, repost_if_unchanged=True
                )
            else:
                await send_lines(bot, message.chat.id, format_session(session))

            return

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

    await send_lines(bot, message.chat.id, lines)


async def send_party_card(
    bot: Bot,
    chat_id: int,
    party_repo: PartyRepository,
    party,
    president_name: str,
    is_creator: bool = False,
    percent: int | None = None,
    influence: int | None = None,
) -> None:
    caption = format_party_card(
        party,
        president_name,
        is_creator=is_creator,
        percent=percent,
        influence=influence,
    )

    photo_bytes: bytes | None = None
    if party.photo_object:
        try:
            photo_bytes = await party_repo.get_photo(party.photo_object)
        except Exception:
            logger.warning("Не удалось загрузить фото партии %s", party.photo_object)
            photo_bytes = None

    if photo_bytes is not None:
        photo = BufferedInputFile(photo_bytes, filename="party.jpg")

        if len(caption) <= PARTY_CAPTION_LIMIT:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
            return

        await send_lines(bot, chat_id, [caption])
        await bot.send_photo(
            chat_id=chat_id, photo=photo, caption=f"🎖 <b>{esc(party.name)}</b>"
        )
        return

    await send_lines(bot, chat_id, [caption])


@router.message(Command("parties"))
async def parties(
    message: Message,
    session_manager: SessionManager,
    party_repo: PartyRepository,
    bot: Bot,
) -> None:
    session = None
    if message.chat.type in GROUP_TYPES:
        session = session_manager.get_by_chat(message.chat.id)

    if session is not None:
        registered = [
            player for player in session.players.values() if player.party is not None
        ]

        if not registered:
            await message.answer("В этой сессии пока нет зарегистрированных партий.")
            return

        in_game = session.status == SessionStatus.IN_GAME
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"<b>Партии сессии <code>{esc(session.code)}</code>:</b>",
        )

        for player in registered:
            assert player.party is not None
            await send_party_card(
                bot,
                message.chat.id,
                party_repo,
                player.party,
                player.public_name,
                is_creator=player.user_id == session.creator_id,
                percent=player.percent if in_game else None,
                influence=player.influence if in_game else None,
            )
        return

    if message.from_user is None:
        return

    try:
        party = await session_manager.get_persisted_party(message.from_user.id)
    except Exception:
        party = None

    if party is None:
        await message.answer(
            "У вас пока нет партии. Зарегистрируйте её в личных сообщениях бота: /reg"
        )
        return

    await send_party_card(
        bot,
        message.chat.id,
        party_repo,
        party,
        message.from_user.full_name,
    )


@router.message(Command("newgame"))
async def newgame(
    message: Message,
    session_manager: SessionManager,
    pack_service: PackService,
    settings: Settings,
    bot: Bot,
) -> None:
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
            display_name=message.from_user.full_name,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось создать сессию: {esc(exc)}")
        return

    session = await try_set_default_pack(session_manager, pack_service, settings, session)
    await send_or_update_lobby(bot, session_manager, session)


@router.message(Command("join"))
async def join(
    message: Message,
    command: CommandObject,
    session_manager: SessionManager,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Присоединяться к игре нужно в групповом чате.")
        return

    if message.from_user is None:
        return

    if command.args:
        code = command.args.strip().upper()
    else:
        session = session_manager.get_by_chat(message.chat.id)

        if session is None:
            await message.answer("В этом чате нет сессии. Создать: /newgame")
            return

        code = session.code

    try:
        result = await session_manager.join(
            code=code,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            username=message.from_user.username,
            display_name=message.from_user.full_name,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось присоединиться: {esc(exc)}")
        return

    if result.already_joined:
        await message.answer("Вы уже в этой сессии.")
    else:
        message_text = f"Игрок присоединился к сессии <code>{esc(result.session.code)}</code>."
        try:
            persisted = await session_manager.get_persisted_party(message.from_user.id)
        except Exception:
            persisted = None
        if persisted is not None:
            message_text += f"\nВаша партия «{esc(persisted.name)}» автоматически применена."
        await message.answer(message_text)

    if result.session.status == SessionStatus.NEW:
        await send_or_update_lobby(bot, session_manager, result.session)


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

    if (
        result.session is not None
        and result.session.status == SessionStatus.NEW
        and not result.closed
    ):
        await send_or_update_lobby(bot, session_manager, result.session)

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
        await message.answer("Использование: /closegame код")
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
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Настройки сессии доступны в групповом чате.")
        return

    if message.from_user is None:
        return

    session = session_manager.get_by_chat(message.chat.id)

    if session is None:
        await message.answer("В этом чате нет игровой сессии.")
        return

    if not command.args:
        lines = [
            "<b>Параметры сессии:</b>",
            "/ss pack id — выбрать пак",
            "/ss turns <число> — выбрать длительность",
        ]

        if session.pack is not None:
            available = ", ".join(str(duration) for duration in session.pack.durations)
            lines.append("")
            lines.append(f"Доступные длительности: {available}")
        else:
            lines.append("")
            lines.append("Пак пока не выбран. Сначала: /ss pack id")

        await send_lines(bot, message.chat.id, lines)
        return

    parts = command.args.strip().split()
    subcommand = parts[0].lower()

    try:
        if subcommand == "pack":
            if len(parts) < 2:
                await message.answer("Использование: /ss pack id")
                return

            pack_id = parts[1].strip()
            meta = await pack_service.get_meta(pack_id)
            pack = await pack_service.load_pack(meta)

            session = await session_manager.set_pack(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                meta=meta,
                pack=pack,
            )

            await message.answer(
                f"Пак {esc(meta.name)} установлен. Ходов: {session.duration}."
            )

            await send_or_update_lobby(bot, session_manager, session)
            return

        if subcommand == "turns":
            if len(parts) < 2:
                await message.answer("Использование: /ss turns число")
                return

            if not parts[1].strip().isdigit():
                await message.answer("Длительность должна быть числом.")
                return

            turns = int(parts[1].strip())

            session = await session_manager.set_duration(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                turns=turns,
            )

            await message.answer(f"Длительность игры установлена: {session.duration} ходов.")
            await send_or_update_lobby(bot, session_manager, session)
            return

        await message.answer("Пока поддерживается только: /ss pack id и /ss turns число")
    except PolIncError as exc:
        await message.answer(f"Не удалось применить настройку: {esc(exc)}")


@router.message(Command("reg"))
async def reg(
    message: Message,
    session_manager: SessionManager,
    state: FSMContext,
    pack_service: PackService,
    bot: Bot,
) -> None:
    if message.chat.type in GROUP_TYPES:
        await message.answer("Регистрация партии происходит в личных сообщениях бота.")
        return

    if message.from_user is None:
        return

    await send_reg_banner(bot, message.chat.id, pack_service)

    session = session_manager.get_by_user(message.from_user.id)

    existing_party = None
    try:
        existing_party = await session_manager.get_persisted_party(message.from_user.id)
    except Exception:
        pass

    if session is not None and session.status != SessionStatus.NEW:
        await message.answer("Регистрировать партию можно только до старта игры.")
        return

    has_existing = existing_party is not None or (session is not None and session.players.get(message.from_user.id) is not None and session.players[message.from_user.id].party is not None)

    if has_existing:
        party_name = ""
        if existing_party is not None:
            party_name = existing_party.name
            await state.update_data(party_name=party_name)
        await message.answer(
            f"У вас уже есть партия «{esc(party_name)}». "
            "Вы можете её перезаписать.\n\n"
            "Шаг 1/5. Отправьте название партии (до 30 символов).\n"
            "Отмена: /cancel"
        )
    else:
        await message.answer(
            "Шаг 1/5. Отправьте название партии (до 30 символов).\n"
            "Отмена: /cancel"
        )

    await state.set_state(RegStates.name)


@router.message(Command("cancel"), F.chat.type == "private")
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Регистрация партии отменена.")


@router.message(RegStates.name, F.chat.type == "private")
async def reg_name(
    message: Message,
    state: FSMContext,
    session_manager: SessionManager,
) -> None:
    if message.from_user is None:
        return

    if not message.text:
        await message.answer("Отправьте название партии текстом.")
        return

    name = message.text.strip()[:30]

    if not name:
        await message.answer("Название партии не может быть пустым. Попробуйте ещё раз.")
        return

    await state.update_data(name=name)
    await state.set_state(RegStates.slogan)

    await message.answer(
        "Шаг 2/5. Отправьте слоган партии (до 50 символов).\n"
        "Если слоган не нужен, отправьте: -"
    )


@router.message(RegStates.slogan, F.chat.type == "private")
async def reg_slogan(
    message: Message,
    state: FSMContext,
    session_manager: SessionManager,
) -> None:
    if message.from_user is None:
        return

    if not message.text:
        await message.answer("Отправьте слоган текстом.")
        return

    slogan = message.text.strip()

    if slogan in {"-", "нет", "пропустить", "-"}:
        slogan = ""
    else:
        slogan = slogan[:50]

    await state.update_data(slogan=slogan)
    await state.set_state(RegStates.ideology)

    await message.answer("Шаг 3/5. Отправьте идеологию партии (до 30 символов).")


@router.message(RegStates.ideology, F.chat.type == "private")
async def reg_ideology(
    message: Message,
    state: FSMContext,
    session_manager: SessionManager,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return

    if not message.text:
        await message.answer("Отправьте идеологию текстом.")
        return

    ideology = message.text.strip()[:30]

    if not ideology:
        await message.answer("Идеология не может быть пустой. Попробуйте ещё раз.")
        return

    await state.update_data(ideology=ideology)
    await state.set_state(RegStates.line)

    await message.answer(
        "Шаг 4/5. Опишите линию партии (до 600 символов).\n"
        "Если линия не нужна, отправьте: -"
    )


@router.message(RegStates.line, F.chat.type == "private")
async def reg_line(
    message: Message,
    state: FSMContext,
) -> None:
    if message.from_user is None:
        return

    if not message.text:
        await message.answer("Отправьте линию партии текстом.")
        return

    line = message.text.strip()

    if line in {"-", "нет", "пропустить", "-"}:
        line = ""
    else:
        line = line[:600]

    await state.update_data(line=line)
    await state.set_state(RegStates.photo)

    await message.answer(
        "Шаг 5/5. Отправьте фотографию партии (только одна, необязательно).",
        reply_markup=_skip_photo_keyboard(),
    )


async def _finish_party_registration(
    state: FSMContext,
    session_manager: SessionManager,
    bot: Bot,
    chat_id: int,
    user_id: int,
    photo_object: str | None,
) -> None:
    data = await state.get_data()
    name = data.get("name", "")
    slogan = data.get("slogan", "")
    ideology = data.get("ideology", "")
    line = data.get("line", "")

    try:
        party = Party.create(
            name=name,
            slogan=slogan,
            ideology=ideology,
            line=line,
            photo_object=photo_object,
        )
        session = await session_manager.register_party(
            user_id=user_id,
            party=party,
        )
    except PolIncError as exc:
        await bot.send_message(
            chat_id=chat_id, text=f"Не удалось зарегистрировать партию: {esc(exc)}"
        )
        return

    await state.clear()

    if session is not None:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Партия «{esc(party.name)}» зарегистрирована "
            f"в сессии <code>{esc(session.code)}</code>.",
        )
        await send_or_update_lobby(bot, session_manager, session)
    else:
        await bot.send_message(
            chat_id=chat_id, text=f"Партия «{esc(party.name)}» зарегистрирована 🫡"
        )


@router.message(RegStates.photo, F.chat.type == "private", F.photo)
async def reg_photo(
    message: Message,
    state: FSMContext,
    session_manager: SessionManager,
    party_repo: PartyRepository,
    bot: Bot,
) -> None:
    if message.from_user is None or not message.photo:
        return

    file_id = message.photo[-1].file_id

    try:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            raise PolIncError("Не удалось получить файл фотографии.")

        downloaded = await bot.download_file(tg_file.file_path)
        if downloaded is None:
            raise PolIncError("Не удалось скачать фотографию.")

        photo_bytes = downloaded.read()
        photo_object = await party_repo.save_photo(message.from_user.id, photo_bytes)
    except PolIncError as exc:
        await message.answer(f"{esc(exc)} Попробуйте ещё раз или нажмите «Пропустить».")
        return
    except Exception:
        logger.exception("Ошибка при загрузке фото партии")
        await message.answer(
            "Не удалось загрузить фотографию. Попробуйте ещё раз или нажмите «Пропустить»."
        )
        return

    await _finish_party_registration(
        state, session_manager, bot, message.chat.id, message.from_user.id, photo_object
    )


@router.callback_query(RegStates.photo, F.data == SKIP_PHOTO_CALLBACK)
async def reg_skip_photo(
    callback: CallbackQuery,
    state: FSMContext,
    session_manager: SessionManager,
    bot: Bot,
) -> None:
    await callback.answer()

    if callback.from_user is None or callback.message is None:
        return

    await _finish_party_registration(
        state,
        session_manager,
        bot,
        callback.message.chat.id,
        callback.from_user.id,
        None,
    )


@router.message(RegStates.photo, F.chat.type == "private")
async def reg_photo_hint(message: Message) -> None:
    await message.answer(
        "Отправьте фотографию партии или нажмите «Пропустить».",
        reply_markup=_skip_photo_keyboard(),
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

    logger.info(
        "/startgame user_id=%s chat_id=%s username=%s",
        message.from_user.id,
        message.chat.id,
        message.from_user.username,
    )

    try:
        session = await session_manager.start_game(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
        )
    except PolIncError as exc:
        await message.answer(f"Не удалось запустить игру: {esc(exc)}")
        return
    except Exception:
        logger.exception("Ошибка при запуске игры")
        await message.answer("Внутренняя ошибка при запуске игры. Проверьте логи.")
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
        await message.answer("Использование: /vote номер")
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
        faction_name = ""
        if command.args.strip().isdigit():
            idx = int(command.args.strip()) - 1
            if 0 <= idx < len(session.pack.factions):
                faction_name = esc(session.pack.factions[idx].name)
        if not faction_name:
            faction_name = esc(command.args)
        await message.answer(f"Голос принят. Вы проголосовали за: {faction_name}.")
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