from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.services.flow import FlowService
from sub_bot.storage.db import session_scope
from sub_bot.storage.repositories import ChatRepository

router = Router()


@router.chat_member()
async def on_chat_member(
    update: ChatMemberUpdated,
    session_factory: async_sessionmaker[AsyncSession],
    flow_service: FlowService,
) -> None:
    if update.new_chat_member.status not in {"member", "restricted"}:
        return
    if update.from_user is None:
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        protected_chat = await repo.get_by_chat_id(update.chat.id)
        if protected_chat is None or not protected_chat.is_enabled:
            return
    await flow_service.handle_join(protected_chat, update.new_chat_member.user)


@router.message()
async def on_message(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    flow_service: FlowService,
) -> None:
    if message.chat.type not in {"group", "supergroup"}:
        return
    if not message.from_user or not message.text:
        return
    if message.text and message.text.startswith("/"):
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        protected_chat = await repo.get_by_chat_id(message.chat.id)
        if protected_chat is None or not protected_chat.is_enabled:
            return
    await flow_service.handle_message_attempt(protected_chat, message)
