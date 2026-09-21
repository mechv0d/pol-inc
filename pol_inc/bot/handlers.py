from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from pol_inc.application.tarbin_packs import TarbinPackService
from pol_inc.application.tarbin_sessions import TarbinSessionManager
from pol_inc.config import Settings
from pol_inc.domain.enums import SessionStatus
from pol_inc.domain.errors import ActionError, PolIncError
from pol_inc.domain.tarbin_game import PRIORITY_DIRECTIONS

from .formatting import (
    PRIORITY_RU,
    esc,
    format_briefing,
    format_event_menu,
    format_final,
    format_help,
    format_lobby,
    format_loy,
    format_pack_list,
    format_regions,
    format_report,
    format_research_menu,
    format_roles_menu,
    format_status,
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
            chunks.append(line[index : index + limit])

        current = ""

    if current:
        chunks.append(current)

    return chunks


async def send_lines(bot: Bot, chat_id: int, lines: list[str]) -> None:
    for chunk in _chunk_lines(lines):
        await bot.send_message(chat_id=chat_id, text=chunk)


async def send_pack_photo(
    bot: Bot,
    chat_id: int,
    pack_service: TarbinPackService,
    object_name: str | None,
    **kwargs,
) -> Message | None:
    """Отправляет изображение из бакета пака. Никогда не бросает исключений."""
    if not object_name:
        return None

    url = None
    try:
        url = pack_service.image_url(object_name)
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось построить URL для %s", object_name)
        url = None

    if url:
        try:
            return await bot.send_photo(chat_id=chat_id, photo=url, **kwargs)
        except Exception:  # noqa: BLE001
            logger.info(
                "Прямая отправка %s не удалась, пробую через скачивание.",
                object_name,
            )

    try:
        data = await pack_service.get_image_bytes(object_name)
    except Exception:
        logger.exception("Не удалось скачать %s из хранилища", object_name)
        return None

    if not data:
        return None

    try:
        filename = object_name.rsplit("/", 1)[-1] or "image.jpg"
        return await bot.send_photo(
            chat_id=chat_id,
            photo=BufferedInputFile(data, filename=filename),
            **kwargs,
        )
    except Exception:
        logger.exception("Не удалось отправить %s в Telegram", object_name)
        return None


async def send_or_update_lobby(
    bot: Bot,
    session_manager: TarbinSessionManager,
    session,
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
                return
            logger.warning("Не удалось отредактировать лобби: %s", exc)
        except Exception:
            logger.exception("Ошибка при редактировании лобби")

    try:
        message = await bot.send_message(chat_id=session.chat_id, text=text)
    except Exception:
        logger.exception("Не удалось отправить лобби")
        return

    try:
        await session_manager.set_lobby_message_id(session.chat_id, message.message_id)
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось сохранить lobby_message_id")


async def try_set_default_pack(
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
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


def _current_event(session) -> tuple:
    if session.pack is None or session.state is None:
        return None, ""
    for event in session.pack.events:
        if event.id == session.state.event_id:
            region_name = ""
            region_id = session.state.event_region_id
            if region_id and region_id in session.state.regions:
                region_name = session.state.regions[region_id].name
            return event, region_name
    return None, ""


def _find_outcome_banner(pack, outcome_id: str) -> str | None:
    if pack is None or not outcome_id:
        return None
    for event in pack.events:
        for option in event.options:
            for outcome in option.outcomes:
                if outcome.id == outcome_id and outcome.banner:
                    return outcome.banner
    return None


async def _send_briefing(
    bot: Bot,
    session,
    pack_service: TarbinPackService,
    session_manager: TarbinSessionManager | None = None,
) -> None:
    event, region_name = _current_event(session)
    if event is not None and event.banner:
        await send_pack_photo(bot, session.chat_id, pack_service, event.banner)
    await send_lines(
        bot, session.chat_id, format_briefing(session, session.pack, event, region_name)
    )


async def _announce_report(
    bot: Bot,
    pack_service: TarbinPackService,
    session,
    report,
) -> None:
    banner = _find_outcome_banner(session.pack, report.outcome_id)
    if banner:
        await send_pack_photo(bot, session.chat_id, pack_service, banner)
    await send_lines(bot, session.chat_id, format_report(report, session.pack))
    if report.result:
        await send_lines(bot, session.chat_id, format_final(session, report))


async def _maybe_resolve_and_announce(
    bot: Bot,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    session,
) -> bool:
    try:
        fresh, report = await session_manager.resolve(session.chat_id)
    except ActionError:
        return False

    await _announce_report(bot, pack_service, fresh, report)
    if not report.result:
        await _send_briefing(bot, fresh, pack_service)
    return True


def _is_commander(session, user_id: int) -> bool:
    return session.role_owners.get("commander") == user_id


def _can_intel(session, user_id: int) -> bool:
    return (
        session.role_owners.get("commander") == user_id
        or session.role_owners.get("intel_chief") == user_id
    )


def _role_short(session, role_id: str) -> str:
    if session.pack is not None:
        role = session.pack.role_by_id(role_id)
        if role is not None:
            return role.short_name or role.name
    return role_id


def _main_menu_kb(session, user_id: int) -> InlineKeyboardMarkup:
    roles = session.roles_of(user_id)
    rows: list[list[InlineKeyboardButton]] = []
    for role_id in roles:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🎬 {_role_short(session, role_id)}",
                    callback_data=f"menu:role:{role_id}",
                )
            ]
        )
    for role_id in roles:
        label = (
            "🔬 Исследования"
            if len(roles) == 1
            else f"🔬 Исследования: {_role_short(session, role_id)}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"menu:res:{role_id}",
                )
            ]
        )
    if session.state is not None and session.state.event_id:
        rows.append(
            [InlineKeyboardButton(text="🗳 Событие", callback_data="menu:event")]
        )
    if _can_intel(session, user_id):
        rows.append(
            [InlineKeyboardButton(text="🛰 Разведка", callback_data="menu:intel")]
        )
    if _is_commander(session, user_id):
        rows.append(
            [InlineKeyboardButton(text="🧭 Приоритет", callback_data="menu:prio")]
        )
    rows.append([InlineKeyboardButton(text="✅ Готов", callback_data="menu:ready")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")]
        ]
    )


def _cb_message(callback: CallbackQuery) -> Message | None:
    message = callback.message
    return message if isinstance(message, Message) else None


async def _refresh_main_menu(callback: CallbackQuery, session, user_id: int) -> None:
    message = _cb_message(callback)
    if message is None:
        return
    try:
        await message.edit_text(
            "\n".join(format_roles_menu(session, user_id)),
            reply_markup=_main_menu_kb(session, user_id),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            logger.warning("Не удалось обновить меню: %s", exc)
    except Exception:
        logger.exception("Ошибка при обновлении меню")


def _require_private(message: Message) -> bool:
    return message.chat.type not in GROUP_TYPES


# ---------- /start ----------


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(
        "<b>TARBIN: Миротворческая миссия</b> — кооперативная штабная игра.\n"
        "Создайте операцию в групповом чате: /newgame\n"
        "Принимайте решения в личных сообщениях: /menu\n"
        "Помощь: /help"
    )


# ---------- Групповые команды ----------


async def send_pack_list(
    bot: Bot,
    chat_id: int,
    pack_service: TarbinPackService,
) -> None:
    try:
        metas = await pack_service.list_metas()
    except PolIncError as exc:
        await send_lines(bot, chat_id, [f"Список паков недоступен: {esc(exc)}"])
        return

    await send_lines(bot, chat_id, format_pack_list(metas))


@router.message(Command("newgame"))
async def newgame(
    message: Message,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    settings: Settings,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Операция создаётся в групповом чате.")
        return
    if message.from_user is None:
        return

    session = await session_manager.create(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        username=message.from_user.username,
        display_name=message.from_user.full_name,
    )
    session = await try_set_default_pack(
        session_manager, pack_service, settings, session
    )
    await send_or_update_lobby(bot, session_manager, session)
    if session.pack is not None and session.pack.assets.cover:
        await send_pack_photo(
            bot, message.chat.id, pack_service, session.pack.assets.cover
        )
    if session.pack is None:
        await send_pack_list(bot, message.chat.id, pack_service)


@router.message(Command("join"))
async def join(
    message: Message,
    command: CommandObject,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Присоединяться к операции нужно в групповом чате.")
        return
    if message.from_user is None:
        return

    if command.args:
        code = command.args.strip().upper()
    else:
        session = session_manager.get_by_chat(message.chat.id)
        if session is None:
            await message.answer("В этом чате нет операции. Создать: /newgame")
            return
        code = session.code

    result = await session_manager.join(
        code=code,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        username=message.from_user.username,
        display_name=message.from_user.full_name,
    )
    if result.already_joined:
        await message.answer("Вы уже в этой операции.")
    else:
        await message.answer(
            f"Вы присоединились к операции <code>{esc(result.session.code)}</code>."
        )
    if result.session.status == SessionStatus.NEW:
        await send_or_update_lobby(bot, session_manager, result.session)


@router.message(Command("leavegame"))
async def leavegame(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if message.from_user is None:
        return

    result = await session_manager.leave(message.from_user.id)

    if result.closed:
        if result.closed_by_creator:
            await message.answer(
                f"Операция <code>{esc(result.code)}</code> закрыта создателем."
            )
        else:
            await message.answer(
                f"Операция <code>{esc(result.code)}</code> закрыта: вышел последний игрок."
            )
        return

    if result.vacated_roles:
        await message.answer(
            f"Вы покинули операцию. Роли вакантны: {esc(', '.join(result.vacated_roles))}."
        )
    else:
        await message.answer("Вы покинули операцию.")

    if result.report is not None and result.session is not None:
        target = result.session.chat_id or message.chat.id
        await send_lines(bot, target, format_report(result.report, result.session.pack))
        if result.report.result:
            await send_lines(bot, target, format_final(result.session, result.report))
    elif result.session is not None and result.session.status == SessionStatus.NEW:
        await send_or_update_lobby(bot, session_manager, result.session)


@router.message(Command("operation"))
async def operation(
    message: Message,
    command: CommandObject,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Название задаётся в групповом чате.")
        return
    if message.from_user is None:
        return
    if not command.args or not command.args.strip():
        await message.answer("Использование: /operation <название>")
        return

    session = await session_manager.set_operation_name(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        name=command.args.strip(),
    )
    await message.answer(f"Операция: <b>{esc(session.operation_name)}</b>")
    await send_or_update_lobby(bot, session_manager, session)


@router.message(Command("startgame"))
async def startgame(
    message: Message,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Игра запускается в групповом чате.")
        return
    if message.from_user is None:
        return

    session = await session_manager.start_game(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
    )
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            "<b>Операция началась!</b>\n"
            "Обсуждайте ситуацию в чате, а решения принимайте "
            "в личных сообщениях бота: /menu"
        ),
    )
    await _send_briefing(bot, session, pack_service)


@router.message(Command("closegame"))
async def closegame(
    message: Message,
    command: CommandObject,
    session_manager: TarbinSessionManager,
) -> None:
    if message.from_user is None:
        return

    code = command.args.strip().upper() if command.args else None
    if not code:
        session = session_manager.get_by_chat(message.chat.id)
        if session is not None:
            code = session.code
    if not code:
        await message.answer("Использование: /closegame [код]")
        return

    session = await session_manager.close(code=code, requester_id=message.from_user.id)
    await message.answer(f"Операция <code>{esc(session.code)}</code> закрыта.")


@router.message(Command("game"))
async def game(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    session = None
    if message.chat.type in GROUP_TYPES:
        session = session_manager.get_by_chat(message.chat.id)
    elif message.from_user is not None:
        session = session_manager.get_by_user(message.from_user.id)

    if session is None:
        if message.chat.type in GROUP_TYPES:
            await message.answer("В этом чате нет операции. Создать: /newgame")
        else:
            await message.answer("Вы не участвуете в операции.")
        return

    if session.status == SessionStatus.NEW:
        if message.chat.type in GROUP_TYPES:
            await send_or_update_lobby(bot, session_manager, session)
        else:
            await send_lines(bot, message.chat.id, format_lobby(session))
    else:
        await send_lines(bot, message.chat.id, format_status(session))


@router.message(Command("ss"))
async def ss(
    message: Message,
    command: CommandObject,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    if message.chat.type not in GROUP_TYPES:
        await message.answer("Настройки сессии доступны в групповом чате.")
        return
    if message.from_user is None:
        return

    session = session_manager.get_by_chat(message.chat.id)
    if session is None:
        await message.answer("В этом чате нет операции.")
        return

    if not command.args:
        lines = [
            "<b>Параметры сессии:</b>",
            "/ss pack id — выбрать пак",
            "/ss turns &lt;число&gt; — длительность операции",
            "",
        ]
        if session.pack is not None:
            available = ", ".join(str(d) for d in session.pack.durations)
            lines.append(f"Доступные длительности: {available}")
            lines.append(f"Текущая: {session.duration} ходов")
        else:
            lines.append("Пак пока не выбран. Сначала: /ss pack id")
        await send_lines(bot, message.chat.id, lines)
        await send_pack_list(bot, message.chat.id, pack_service)
        return

    parts = command.args.strip().split()
    sub = parts[0].lower()

    if sub == "pack":
        if len(parts) < 2:
            await message.answer("Использование: /ss pack id")
            return
        meta = await pack_service.get_meta(parts[1].strip())
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

    if sub == "turns":
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await message.answer("Использование: /ss turns число")
            return
        session = await session_manager.set_duration(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            turns=int(parts[1].strip()),
        )
        await message.answer(f"Длительность установлена: {session.duration} ходов.")
        await send_or_update_lobby(bot, session_manager, session)
        return

    await message.answer("Поддерживается: /ss pack id и /ss turns число")


@router.message(Command("status"))
async def status(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    session = None
    if message.chat.type in GROUP_TYPES:
        session = session_manager.get_by_chat(message.chat.id)
    elif message.from_user is not None:
        session = session_manager.get_by_user(message.from_user.id)

    if session is None:
        await message.answer("Нет активной операции.")
        return
    await send_lines(bot, message.chat.id, format_status(session))


@router.message(Command("help"))
async def help_cmd(message: Message, bot: Bot) -> None:
    await send_lines(bot, message.chat.id, format_help())


# ---------- Личные команды ----------


def _user_session(session_manager: TarbinSessionManager, user_id: int):
    return session_manager.get_by_user(user_id)


@router.message(Command("menu"))
async def menu(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Меню штаба доступно в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return
    if session.status != SessionStatus.IN_GAME or session.state is None:
        await message.answer("Игра ещё не запущена. Дождитесь /startgame в группе.")
        return

    await bot.send_message(
        chat_id=message.chat.id,
        text="\n".join(format_roles_menu(session, message.from_user.id)),
        reply_markup=_main_menu_kb(session, message.from_user.id),
    )


@router.message(Command("actions"))
async def actions(
    message: Message,
    command: CommandObject,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Действия выбираются в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return
    if session.status != SessionStatus.IN_GAME or session.state is None:
        await message.answer("Игра ещё не запущена.")
        return

    roles = session.roles_of(message.from_user.id)
    if not roles:
        await message.answer("У вас нет ролей в этой операции.")
        return

    if command.args and command.args.strip().isdigit():
        index = int(command.args.strip()) - 1
        if 0 <= index < len(roles):
            roles = [roles[index]]
        else:
            await message.answer(
                f"Ролей у вас: {len(roles)}. Укажите номер от 1 до {len(roles)}."
            )
            return

    lines = ["<b>Ваши действия на этом ходу:</b>", ""]
    for role_id in roles:
        lines.append(f"<b>{esc(_role_short(session, role_id))}:</b>")
        options = session_manager.action_options(session, role_id)
        if not options:
            lines.append("- нет доступных действий")
        for opt in options:
            if opt.locked_reason:
                lines.append(
                    f"🔒 {esc(opt.name)} — {opt.cost} млн ({esc(opt.locked_reason)})"
                )
            else:
                lines.append(
                    f"- {esc(opt.name)} (<code>{esc(opt.action_id)}</code>) — {opt.cost} млн"
                )
        lines.append("")
    lines.append("Выберите действие через /menu.")
    await send_lines(bot, message.chat.id, lines)


@router.message(Command("research"))
async def research(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Исследования выбираются в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return
    if session.status != SessionStatus.IN_GAME or session.state is None:
        await message.answer("Игра ещё не запущена.")
        return

    await send_lines(bot, message.chat.id, format_research_menu(session))


@router.message(Command("regions"))
async def regions(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Сводка по регионам — в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return
    if session.status != SessionStatus.IN_GAME or session.state is None:
        await message.answer("Игра ещё не запущена.")
        return

    show_hideouts = _can_intel(session, message.from_user.id)
    await send_lines(bot, message.chat.id, format_regions(session, show_hideouts))


@router.message(Command("event"))
async def event(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Голосование проходит в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return
    if session.status != SessionStatus.IN_GAME or session.state is None:
        await message.answer("Игра ещё не запущена.")
        return
    if not session.state.event_id:
        await message.answer("Сейчас нет активного события.")
        return

    kb_rows: list[list[InlineKeyboardButton]] = []
    if session.pack is not None:
        for ev in session.pack.events:
            if ev.id == session.state.event_id:
                for option in ev.options:
                    kb_rows.append(
                        [
                            InlineKeyboardButton(
                                text=f"{option.id} — {option.title} ({option.cost} млн)",
                                callback_data=f"menu:vote:{option.id}",
                            )
                        ]
                    )
                break
    await bot.send_message(
        chat_id=message.chat.id,
        text="\n".join(format_event_menu(session)),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None,
    )


@router.message(Command("confirm"))
async def confirm(
    message: Message,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Подтверждение — в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return

    should_resolve = await session_manager.confirm(message.from_user.id)
    await message.answer("Готов! ✅ Ждём остальных членов штаба.")
    if should_resolve:
        await _maybe_resolve_and_announce(bot, session_manager, pack_service, session)


@router.message(Command("cancel"))
async def cancel(
    message: Message,
    session_manager: TarbinSessionManager,
) -> None:
    if not _require_private(message):
        await message.answer("Сброс заявок — в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    await session_manager.reset_turn(message.from_user.id)
    await message.answer("Заявки этого хода сброшены.")


@router.message(Command("loy"))
async def loy(
    message: Message,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    if not _require_private(message):
        await message.answer("Личная карточка — в личных сообщениях бота.")
        return
    if message.from_user is None:
        return

    session = _user_session(session_manager, message.from_user.id)
    if session is None:
        await message.answer("Вы не участвуете в операции.")
        return

    await send_lines(bot, message.chat.id, format_loy(session, message.from_user.id))


# ---------- Callback'и ----------


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "menu:back")
async def cb_back(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        if callback.from_user is None:
            return
        await callback.answer()
        session = _user_session(session_manager, callback.from_user.id)
        if session is None or session.state is None:
            return
        await _refresh_main_menu(callback, session, callback.from_user.id)
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:role:"))
async def cb_role(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        await callback.answer()
        session = _user_session(session_manager, callback.from_user.id)
        if session is None or session.state is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            return
        role_id = parts[2]
        options = session_manager.action_options(session, role_id)
        lines = [f"<b>{esc(_role_short(session, role_id))}. Выберите действие:</b>", ""]
        rows: list[list[InlineKeyboardButton]] = []
        for opt in options:
            if opt.locked_reason:
                lines.append(
                    f"🔒 {esc(opt.name)} — {opt.cost} млн ({esc(opt.locked_reason)})"
                )
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"🔒 {opt.name}",
                            callback_data="noop",
                        )
                    ]
                )
            else:
                lines.append(f"- {esc(opt.name)} — {opt.cost} млн")
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"{opt.name} ({opt.cost} млн)",
                            callback_data=f"menu:act:{role_id}:{opt.action_id}",
                        )
                    ]
                )
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")])
        await message.edit_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:act:"))
async def cb_act(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 4:
            return
        _, _, role_id, action_id = parts
        session = _user_session(session_manager, callback.from_user.id)
        if session is None or session.state is None or session.pack is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        action = session.pack.action_by_id(action_id)
        if action is None:
            await callback.answer("Действие не найдено.", show_alert=True)
            return
        if action.target == "region":
            rows: list[list[InlineKeyboardButton]] = []
            for region in session.state.regions.values():
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=region.name,
                            callback_data=f"menu:reg:{role_id}:{action_id}:{region.region_id}",
                        )
                    ]
                )
            rows.append(
                [InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")]
            )
            await callback.answer()
            await message.edit_text(
                f"<b>{esc(action.name)}</b>. Выберите регион:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
            )
            return
        should_resolve = await session_manager.submit_action(
            callback.from_user.id, role_id, action_id, ""
        )
        await callback.answer(f"Заявка принята: {action.name}")
        await _refresh_main_menu(callback, session, callback.from_user.id)
        if should_resolve:
            await _maybe_resolve_and_announce(
                bot, session_manager, pack_service, session
            )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:reg:"))
async def cb_reg(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 5:
            return
        _, _, role_id, action_id, region_id = parts
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        should_resolve = await session_manager.submit_action(
            callback.from_user.id, role_id, action_id, region_id
        )
        await callback.answer("Заявка принята.")
        await _refresh_main_menu(callback, session, callback.from_user.id)
        if should_resolve:
            await _maybe_resolve_and_announce(
                bot, session_manager, pack_service, session
            )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:res:"))
async def cb_res(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        await callback.answer()
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            return
        role_id = parts[2]
        session = _user_session(session_manager, callback.from_user.id)
        if session is None or session.state is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        options = session_manager.research_options(session, role_id)
        lines = [f"<b>Исследования ({esc(_role_short(session, role_id))}):</b>", ""]
        rows: list[list[InlineKeyboardButton]] = []
        for opt in options:
            if opt.locked_reason:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"🔒 {opt.name}",
                            callback_data="noop",
                        )
                    ]
                )
            else:
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"{opt.name} ({opt.cost} млн)",
                            callback_data=f"menu:tech:{role_id}:{opt.tech_id}",
                        )
                    ]
                )
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")])
        await message.edit_text(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:tech:"))
async def cb_tech(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 4:
            return
        _, _, role_id, tech_id = parts
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        should_resolve = await session_manager.submit_research(
            callback.from_user.id, role_id, tech_id
        )
        await callback.answer("Исследование заявлено.")
        await _refresh_main_menu(callback, session, callback.from_user.id)
        if should_resolve:
            await _maybe_resolve_and_announce(
                bot, session_manager, pack_service, session
            )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "menu:event")
async def cb_event(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        await callback.answer()
        session = _user_session(session_manager, callback.from_user.id)
        if session is None or session.state is None or session.pack is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        if not session.state.event_id:
            await callback.answer("Сейчас нет активного события.", show_alert=True)
            return
        rows: list[list[InlineKeyboardButton]] = []
        for event in session.pack.events:
            if event.id == session.state.event_id:
                for option in event.options:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                text=f"{option.id} — {option.title}",
                                callback_data=f"menu:vote:{option.id}",
                            )
                        ]
                    )
                break
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")])
        await message.edit_text(
            "\n".join(format_event_menu(session)),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:vote:"))
async def cb_vote(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
    bot: Bot,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            return
        option_id = parts[2]
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        await session_manager.vote_event(callback.from_user.id, option_id)
        await callback.answer(f"Голос принят: {option_id}")
        await _refresh_main_menu(callback, session, callback.from_user.id)
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "menu:ready")
async def cb_ready(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
    pack_service: TarbinPackService,
    bot: Bot,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        should_resolve = await session_manager.confirm(callback.from_user.id)
        await callback.answer("Готов! ✅")
        if should_resolve:
            await _maybe_resolve_and_announce(
                bot, session_manager, pack_service, session
            )
        else:
            await _refresh_main_menu(callback, session, callback.from_user.id)
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "menu:intel")
async def cb_intel(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        await callback.answer()
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        intentions, regions, hideouts = session_manager.intel_brief(session)
        lines = ["<b>🛰 Сводка разведки:</b>", ""]
        if intentions:
            lines.append("<b>Намерения Al Nazra:</b>")
            for item in intentions:
                lines.append(f"- {esc(item)}")
        else:
            lines.append("Намерения Al Nazra пока не раскрыты.")
        lines.append("")
        if regions:
            lines.append(f"Разведанные регионы: {esc(', '.join(regions))}")
        else:
            lines.append("Разведанных регионов пока нет.")
        lines.append(f"Подтверждено логовов: {hideouts}")
        await message.edit_text("\n".join(lines), reply_markup=_back_kb())
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "menu:prio")
async def cb_prio(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        await callback.answer()
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        rows: list[list[InlineKeyboardButton]] = []
        for direction in PRIORITY_DIRECTIONS:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=PRIORITY_RU.get(direction, direction),
                        callback_data=f"menu:prio:{direction}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu:back")])
        await message.edit_text(
            "<b>🧭 Приоритет операции:</b>\nСоответствующие действия получат бонус.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data.startswith("menu:prio:"))
async def cb_prio_set(
    callback: CallbackQuery,
    session_manager: TarbinSessionManager,
) -> None:
    try:
        message = _cb_message(callback)
        if callback.from_user is None or message is None:
            return
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            return
        direction = parts[2]
        session = _user_session(session_manager, callback.from_user.id)
        if session is None:
            await callback.answer("Нет активной игры.", show_alert=True)
            return
        await session_manager.set_priority(callback.from_user.id, direction)
        await callback.answer(f"Приоритет: {PRIORITY_RU.get(direction, direction)}")
        await _refresh_main_menu(callback, session, callback.from_user.id)
    except PolIncError as exc:
        await callback.answer(str(exc), show_alert=True)
