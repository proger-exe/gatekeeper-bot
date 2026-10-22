from __future__ import annotations

import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError

from sub_bot.services.cleanup import CleanupWorker


class CleanupWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_delete_error_does_not_stop_worker(self) -> None:
        task = SimpleNamespace(id=1, chat_id=-100123, message_id=55)
        repo = Mock()
        repo.fetch_due_cleanup_tasks = AsyncMock(return_value=[task])
        repo.delete_cleanup_task = AsyncMock()

        bot = Mock()
        bot.delete_message = AsyncMock(
            side_effect=TelegramForbiddenError(Mock(), "message can't be deleted")
        )
        worker = CleanupWorker(bot, session_factory=object(), poll_interval_seconds=0)

        @asynccontextmanager
        async def fake_session_scope(_session_factory: object):
            yield object()

        with (
            patch("sub_bot.services.cleanup.session_scope", fake_session_scope),
            patch("sub_bot.services.cleanup.ChatRepository", return_value=repo),
            patch(
                "sub_bot.services.cleanup.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await worker.run()

        repo.delete_cleanup_task.assert_awaited_once_with(task.id)

    async def test_transient_delete_error_keeps_task_in_queue(self) -> None:
        task = SimpleNamespace(id=2, chat_id=-100123, message_id=77)
        repo = Mock()
        repo.fetch_due_cleanup_tasks = AsyncMock(return_value=[task])
        repo.delete_cleanup_task = AsyncMock()

        bot = Mock()
        bot.delete_message = AsyncMock(
            side_effect=TelegramNetworkError(Mock(), "temporary network failure")
        )
        worker = CleanupWorker(bot, session_factory=object(), poll_interval_seconds=0)

        @asynccontextmanager
        async def fake_session_scope(_session_factory: object):
            yield object()

        with (
            patch("sub_bot.services.cleanup.session_scope", fake_session_scope),
            patch("sub_bot.services.cleanup.ChatRepository", return_value=repo),
            patch(
                "sub_bot.services.cleanup.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await worker.run()

        repo.delete_cleanup_task.assert_not_awaited()
