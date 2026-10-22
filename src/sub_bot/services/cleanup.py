from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.storage.db import session_scope
from sub_bot.storage.repositories import ChatRepository

logger = logging.getLogger(__name__)


class CleanupWorker:
    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession], poll_interval_seconds: int = 5):
        self.bot = bot
        self.session_factory = session_factory
        self.poll_interval_seconds = poll_interval_seconds

    async def run(self) -> None:
        while True:
            try:
                async with session_scope(self.session_factory) as session:
                    repo = ChatRepository(session)
                    tasks = await repo.fetch_due_cleanup_tasks()
                    for task in tasks:
                        should_drop_task = await self._delete_message(task.chat_id, task.message_id)
                        if should_drop_task:
                            await repo.delete_cleanup_task(task.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cleanup worker iteration failed")
            await asyncio.sleep(self.poll_interval_seconds)

    async def _delete_message(self, chat_id: int, message_id: int) -> bool:
        try:
            await self.bot.delete_message(chat_id, message_id)
            return True
        except (TelegramBadRequest, TelegramForbiddenError):
            return True
        except (TelegramRetryAfter, TelegramNetworkError, TelegramServerError):
            logger.warning(
                "cleanup worker will retry message deletion for chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
            return False
        except Exception:
            logger.exception(
                "cleanup worker hit unexpected error for chat_id=%s message_id=%s",
                chat_id,
                message_id,
            )
            return False
