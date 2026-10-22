from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.services.telegram_access import AccessService
from sub_bot.storage.db import session_scope
from sub_bot.storage.repositories import ChatRepository


class UnmuteWorker:
    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession], poll_interval_seconds: int = 5):
        self.bot = bot
        self.session_factory = session_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.access_service = AccessService(bot, session_factory)

    async def run(self) -> None:
        while True:
            async with session_scope(self.session_factory) as session:
                repo = ChatRepository(session)
                tasks = await repo.fetch_due_unmute_tasks()
                for task in tasks:
                    protected_chat = await repo.get_by_id(task.protected_chat_id)
                    if protected_chat is None:
                        await repo.delete_unmute_task(task.id)
                        continue

                    try:
                        await self.access_service.unrestrict_member(protected_chat, task.user_id)
                        state = await repo.get_or_create_state(protected_chat.id, task.user_id)
                        state.is_restricted = False
                        state.current_penalty_level = 0
                        await repo.append_audit(protected_chat.id, task.user_id, "unmuted", {})
                    except (TelegramBadRequest, TelegramForbiddenError):
                        await repo.append_audit(protected_chat.id, task.user_id, "unmute_skipped", {})
                    await repo.delete_unmute_task(task.id)
            await asyncio.sleep(self.poll_interval_seconds)
