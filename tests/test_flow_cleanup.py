from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from sub_bot.services.flow import FlowService


class FlowCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_message_later_removes_message_after_delay(self) -> None:
        bot = Mock()
        bot.delete_message = AsyncMock()
        service = FlowService(bot, session_factory=object(), access_service=Mock())

        with patch("sub_bot.services.flow.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            await service._delete_message_later(-100123, 55, 120)

        sleep_mock.assert_awaited_once_with(120)
        bot.delete_message.assert_awaited_once_with(-100123, 55)

    async def test_delete_message_later_ignores_telegram_delete_errors(self) -> None:
        for error in (
            TelegramBadRequest(Mock(), "message to delete not found"),
            TelegramForbiddenError(Mock(), "not enough rights to delete message"),
        ):
            bot = Mock()
            bot.delete_message = AsyncMock(side_effect=error)
            service = FlowService(bot, session_factory=object(), access_service=Mock())

            with self.subTest(error_type=type(error).__name__):
                with patch("sub_bot.services.flow.asyncio.sleep", new=AsyncMock()):
                    await service._delete_message_later(-100123, 77, 60)

            bot.delete_message.assert_awaited_once_with(-100123, 77)
