from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    User,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from sub_bot.storage.db import session_scope
from sub_bot.storage.models import ProtectedChat
from sub_bot.storage.repositories import ChatRepository
from sub_bot.time_utils import utc_now


@dataclass(slots=True)
class AccessCheckResult:
    status: str
    missing_targets: list[str]


class AccessService:
    IGNORED_USER_IDS = {777000}

    def __init__(self, bot: Bot, session_factory: async_sessionmaker[AsyncSession]):
        self.bot = bot
        self.session_factory = session_factory

    async def is_exempt(self, protected_chat: ProtectedChat, user: User) -> bool:
        if user.id in self.IGNORED_USER_IDS:
            return True
        if user.is_bot:
            return True

        member = await self.bot.get_chat_member(protected_chat.chat_id, user.id)
        if member.status in {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR}:
            return True

        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            return await repo.is_whitelisted(protected_chat.id, user.id)

    async def check_memberships(
        self, protected_chat: ProtectedChat, user_id: int, force: bool = False
    ) -> AccessCheckResult:
        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            if not force:
                cached_state = await repo.get_recent_subscription_state(
                    protected_chat.id,
                    user_id,
                    protected_chat.subscription_cache_ttl_sec,
                )
                if cached_state is not None:
                    return AccessCheckResult(
                        status=cached_state.last_subscription_status,
                        missing_targets=[],
                    )

            targets = await repo.list_targets(protected_chat.id)
            missing_targets: list[str] = []
            for target in targets:
                if not target.is_active or not target.is_valid:
                    continue

                target_ref = (
                    target.target_chat_id
                    if target.target_chat_id is not None
                    else f"@{target.target_username}"
                )
                try:
                    member = await self.bot.get_chat_member(target_ref, user_id)
                except (TelegramBadRequest, TelegramForbiddenError):
                    target.is_valid = False
                    missing_targets.append(target.target_title or str(target_ref))
                    continue

                if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
                    missing_targets.append(target.target_title or str(target_ref))

            state = await repo.get_or_create_state(protected_chat.id, user_id)
            state.last_subscription_status = "ok" if not missing_targets else "failed"
            state.last_checked_at = utc_now()
            return AccessCheckResult(
                status=state.last_subscription_status, missing_targets=missing_targets
            )

    async def restrict_member(
        self, protected_chat: ProtectedChat, user_id: int, seconds: int
    ) -> None:
        await self.bot.restrict_chat_member(
            protected_chat.chat_id,
            user_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_send_polls=False,
            ),
            use_independent_chat_permissions=False,
            until_date=self._build_until_date(seconds),
        )

    async def unrestrict_member(
        self, protected_chat: ProtectedChat, user_id: int
    ) -> None:
        await self.bot.restrict_chat_member(
            protected_chat.chat_id,
            user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
            ),
        )

    async def mute_member(
        self, protected_chat: ProtectedChat, user_id: int, seconds: int
    ) -> None:
        await self.restrict_member(protected_chat, user_id, seconds)

    def _build_until_date(self, seconds: int):
        return timedelta(seconds=seconds)

    def build_notice_markup(
        self, protected_chat: ProtectedChat, targets: list[tuple[str, str]]
    ) -> InlineKeyboardMarkup:
        rows = [[InlineKeyboardButton(text=title, url=url)] for title, url in targets]
        rows.append(
            [
                InlineKeyboardButton(
                    text="Проверить подписку",
                    callback_data=f"recheck:{protected_chat.chat_id}",
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)
