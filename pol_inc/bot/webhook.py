from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, Update
from fastapi import FastAPI, HTTPException, Request

from pol_inc.application.tarbin_packs import TarbinPackService
from pol_inc.application.tarbin_sessions import TarbinSessionManager
from pol_inc.config import get_settings
from pol_inc.infrastructure.supabase import SupabaseStorageClient

from .dp import create_dispatcher

logger = logging.getLogger(__name__)

settings = get_settings()

logging.basicConfig(level=settings.log_level)


async def cleanup_sessions(bot: Bot, session_manager: TarbinSessionManager) -> None:
    while True:
        await asyncio.sleep(300)

        expired_sessions = await session_manager.close_expired()

        for session in expired_sessions:
            try:
                await bot.send_message(
                    session.chat_id,
                    f"Сессия {session.code} закрыта по истечении времени. "
                    "Всем засчитано техническое поражение.",
                )
            except Exception:
                logger.exception("Не удалось отправить сообщение о закрытии сессии.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = SupabaseStorageClient(settings)
    pack_service = TarbinPackService(storage=storage, settings=settings)
    session_manager = TarbinSessionManager(settings=settings)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = create_dispatcher(
        storage=MemoryStorage(),
        settings=settings,
        session_manager=session_manager,
        pack_service=pack_service,
    )

    app.state.bot = bot
    app.state.dp = dp
    app.state.storage = storage

    await bot.set_my_commands(
        [
            BotCommand(command="game", description="Лобби или статус игры"),
            BotCommand(command="newgame", description="Создать операцию"),
            BotCommand(command="join", description="Присоединиться к операции"),
            BotCommand(command="leavegame", description="Покинуть операцию"),
            BotCommand(command="operation", description="Название операции"),
            BotCommand(command="startgame", description="Запустить игру"),
            BotCommand(command="closegame", description="Закрыть операцию"),
            BotCommand(command="ss", description="Параметры сессии"),
            BotCommand(command="status", description="Снимок состояния"),
            BotCommand(command="menu", description="Меню штаба (ЛС)"),
            BotCommand(command="actions", description="Действия ролей (ЛС)"),
            BotCommand(command="research", description="Технологии (ЛС)"),
            BotCommand(command="regions", description="Регионы (ЛС)"),
            BotCommand(command="event", description="Голосование (ЛС)"),
            BotCommand(command="confirm", description="Готов (ЛС)"),
            BotCommand(command="cancel", description="Сбросить заявки (ЛС)"),
            BotCommand(command="loy", description="Личная карточка (ЛС)"),
            BotCommand(command="help", description="Помощь"),
        ]
    )

    cleanup_task = asyncio.create_task(cleanup_sessions(bot, session_manager))

    if settings.telegram_webhook_enabled:
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.telegram_webhook_secret,
            drop_pending_updates=False,
        )
        logger.info("Telegram webhook set to %s", settings.webhook_url)
    else:
        logger.warning("Telegram webhook disabled by settings.")

    try:
        yield
    finally:
        cleanup_task.cancel()

        with suppress(asyncio.CancelledError):
            await cleanup_task

        await bot.session.close()
        await storage.aclose()


app = FastAPI(title="POL Inc. bot", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.head("/healthz")
async def healthz_head() -> None:
    return None


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "POL Inc. bot",
        "health": "/healthz",
    }


@app.post(settings.telegram_webhook_path)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")

    if secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    update = Update.model_validate(payload)
    await dp.feed_update(bot=bot, update=update)

    return {"ok": True}
