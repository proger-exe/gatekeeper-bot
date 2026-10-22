from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.services.flow import FlowService
from sub_bot.storage.db import session_scope
from sub_bot.storage.repositories import ChatRepository

router = Router()


@router.callback_query(F.data.startswith("recheck:"))
async def recheck_subscription(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    flow_service: FlowService,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    chat_id = int(callback.data.split(":", maxsplit=1)[1])
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        protected_chat = await repo.get_by_chat_id(chat_id)
        if protected_chat is None:
            await callback.answer("Чат не настроен.", show_alert=True)
            return
    status, missing = await flow_service.recheck_access(protected_chat, callback.from_user)
    if status == "ok":
        await callback.answer("Доступ открыт.", show_alert=False)
    else:
        await callback.answer("Подписки всё ещё не хватает.", show_alert=True)
