from __future__ import annotations

import logging
from html import escape

from aiogram import Dispatcher
from aiogram.fsm.storage.base import Storage
from aiogram.types import ErrorEvent

from pol_inc.domain.errors import PolIncError

from .handlers import router as commands_router

logger = logging.getLogger(__name__)


def create_dispatcher(storage: Storage | None = None, **workflow_data) -> Dispatcher:
    dp = Dispatcher(storage=storage, **workflow_data)
    dp.include_router(commands_router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        update = event.update
        message = None

        if update is not None:
            message = update.message or update.edited_message or update.channel_post

        exc = event.exception

        if isinstance(exc, PolIncError):
            if message is not None:
                await message.answer(f"Ошибка: {escape(str(exc))}")
            return True

        logger.exception("Unhandled error: %s", exc)

        if message is not None:
            await message.answer("Внутренняя ошибка. Попробуйте позже.")

        return True

    return dp