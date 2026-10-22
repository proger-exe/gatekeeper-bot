from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sub_bot.config import get_settings
from sub_bot.handlers.admin import router as admin_router
from sub_bot.handlers.callbacks import router as callbacks_router
from sub_bot.handlers.chat import router as chat_router
from sub_bot.logging import configure_logging
from sub_bot.services.flow import FlowService
from sub_bot.services.telegram_access import AccessService
from sub_bot.services.unmute import UnmuteWorker
from sub_bot.storage.db import build_engine, build_session_factory
from sub_bot.storage.models import Base


async def bootstrap_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    await bootstrap_database(engine)

    access_service = AccessService(bot, session_factory)
    flow_service = FlowService(bot, session_factory, access_service)
    unmute_worker = UnmuteWorker(bot, session_factory)

    dispatcher = Dispatcher()
    dispatcher["session_factory"] = session_factory
    dispatcher["settings"] = settings
    dispatcher["flow_service"] = flow_service
    dispatcher.include_router(admin_router)
    dispatcher.include_router(callbacks_router)
    dispatcher.include_router(chat_router)

    unmute_task = asyncio.create_task(unmute_worker.run(), name="unmute-worker")
    try:
        await dispatcher.start_polling(bot)
    finally:
        unmute_task.cancel()
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
