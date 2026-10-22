from __future__ import annotations

import asyncio
import html

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.storage.db import session_scope
from sub_bot.storage.models import ProtectedChat
from sub_bot.storage.repositories import ChatRepository
from sub_bot.services.telegram_access import AccessService
from sub_bot.time_utils import utc_now


class FlowService:
    DEFAULT_MUTE_SECONDS = 60

    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        access_service: AccessService,
    ):
        self.bot = bot
        self.session_factory = session_factory
        self.access_service = access_service
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def handle_join(self, protected_chat: ProtectedChat, user: User) -> None:
        "Useless function, but saved"
        return

        if await self.access_service.is_exempt(protected_chat, user):
            return

        result = await self.access_service.check_memberships(
            protected_chat, user.id, force=True
        )
        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            state = await repo.get_or_create_state(protected_chat.id, user.id)
            state.last_subscription_status = result.status
            state.last_checked_at = utc_now()
            if result.status == "failed":
                await self.access_service.restrict_member(
                    protected_chat,
                    user.id,
                    self._choose_mute_seconds(protected_chat),
                )
                state.is_restricted = True
                await repo.append_audit(
                    protected_chat.id,
                    user.id,
                    "restricted_on_join",
                    {"missing_targets": result.missing_targets},
                )
                await self._send_notice(
                    session, repo, protected_chat, user, result.missing_targets
                )

    async def handle_message_attempt(
        self, protected_chat: ProtectedChat, message: Message
    ) -> None:
        if not message.from_user or not message.text:
            return
        if await self.access_service.is_exempt(protected_chat, message.from_user):
            return

        result = await self.access_service.check_memberships(
            protected_chat, message.from_user.id
        )
        if result.status == "ok":
            await self._ensure_unrestricted(protected_chat, message.from_user.id)
            return

        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            state = await repo.get_or_create_state(
                protected_chat.id, message.from_user.id
            )
            state.last_subscription_status = "failed"
            state.last_checked_at = utc_now()
            state.is_restricted = True

            try:
                await self.bot.delete_message(message.chat.id, message.message_id)
            except TelegramBadRequest:
                pass

            await self.access_service.restrict_member(
                protected_chat,
                message.from_user.id,
                self._choose_mute_seconds(protected_chat),
            )
            await repo.add_violation(
                protected_chat.id,
                message.from_user.id,
                "not_subscribed_message_attempt",
            )
            violations = await repo.count_recent_violations(
                protected_chat.id,
                message.from_user.id,
                "not_subscribed_message_attempt",
                protected_chat.mute_window_sec,
            )
            await repo.append_audit(
                protected_chat.id,
                message.from_user.id,
                "message_deleted",
                {"violations": violations},
            )

            if violations >= 3:
                mute_seconds = self._choose_mute_seconds(protected_chat)
                await self.access_service.mute_member(
                    protected_chat, message.from_user.id, mute_seconds
                )
                state.current_penalty_level = 1
                await repo.append_audit(
                    protected_chat.id,
                    message.from_user.id,
                    "muted",
                    {"mute_seconds": mute_seconds},
                )

            await self._send_notice(
                session, repo, protected_chat, message.from_user, result.missing_targets
            )

    async def recheck_access(
        self, protected_chat: ProtectedChat, user: User
    ) -> tuple[str, list[str]]:
        result = await self.access_service.check_memberships(
            protected_chat, user.id, force=True
        )
        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            state = await repo.get_or_create_state(protected_chat.id, user.id)
            state.last_subscription_status = result.status
            state.last_checked_at = utc_now()

            if result.status == "ok":
                state.is_restricted = False
                state.current_penalty_level = 0
                await repo.delete_user_unmute_task(protected_chat.id, user.id)
                await self.access_service.unrestrict_member(protected_chat, user.id)
                await repo.append_audit(
                    protected_chat.id, user.id, "access_granted", {}
                )
                if state.last_notice_message_id:
                    try:
                        await self.bot.delete_message(
                            protected_chat.chat_id, state.last_notice_message_id
                        )
                    except TelegramBadRequest:
                        pass
                    state.last_notice_message_id = None
                return "ok", []

            await self.access_service.restrict_member(
                protected_chat,
                user.id,
                self._choose_mute_seconds(protected_chat),
            )
            state.is_restricted = True
            await self._send_notice(
                session, repo, protected_chat, user, result.missing_targets
            )
            return "failed", result.missing_targets

    async def _ensure_unrestricted(
        self, protected_chat: ProtectedChat, user_id: int
    ) -> None:
        async with session_scope(self.session_factory) as session:
            repo = ChatRepository(session)
            state = await repo.get_or_create_state(protected_chat.id, user_id)
            if state.is_restricted or state.current_penalty_level > 0:
                await repo.delete_user_unmute_task(protected_chat.id, user_id)
                await self.access_service.unrestrict_member(protected_chat, user_id)
                state.is_restricted = False
                state.current_penalty_level = 0
                await repo.append_audit(
                    protected_chat.id,
                    user_id,
                    "access_granted",
                    {"source": "message_recheck"},
                )

    async def _send_notice(
        self,
        session: AsyncSession,
        repo: ChatRepository,
        protected_chat: ProtectedChat,
        user: User,
        missing_targets: list[str],
    ) -> None:
        state = await repo.get_or_create_state(protected_chat.id, user.id)
        now = utc_now()
        if (
            state.last_notice_at
            and (now - state.last_notice_at).total_seconds()
            < protected_chat.notification_cooldown_sec
        ):
            return

        targets = await repo.list_targets(protected_chat.id)
        button_targets: list[tuple[str, str]] = []
        for target in targets:
            if not target.is_active:
                continue
            if target.target_username:
                button_targets.append(
                    (
                        target.target_title or f"@{target.target_username}",
                        f"https://t.me/{target.target_username}",
                    )
                )

        text = (
            f'<a href="tg://user?id={user.id}">{html.escape(user.first_name)}</a>, '
            "чтобы писать в этом чате, подпишись на обязательные каналы ниже и нажми «Проверить подписку»."
        )
        if missing_targets:
            text += "\n\nНе хватает:\n" + "\n".join(
                f"• {item}" for item in missing_targets
            )
        message = await self.bot.send_message(
            protected_chat.chat_id,
            text,
            reply_markup=self.access_service.build_notice_markup(
                protected_chat, button_targets
            ),
        )
        state.last_notice_at = now
        state.last_notice_message_id = message.message_id
        self._schedule_message_cleanup(
            protected_chat.chat_id,
            message.message_id,
            protected_chat.notification_ttl_sec,
        )
        await repo.append_audit(
            protected_chat.id,
            user.id,
            "notice_sent",
            {"missing_targets": missing_targets},
        )

    def _choose_mute_seconds(self, protected_chat: ProtectedChat) -> int:
        if protected_chat.mute_step_seconds:
            return protected_chat.mute_step_seconds[0]
        return self.DEFAULT_MUTE_SECONDS

    def _schedule_message_cleanup(
        self, chat_id: int, message_id: int, delay_seconds: int
    ) -> None:
        task = asyncio.create_task(
            self._delete_message_later(chat_id, message_id, delay_seconds)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _delete_message_later(
        self, chat_id: int, message_id: int, delay_seconds: int
    ) -> None:
        await asyncio.sleep(delay_seconds)
        try:
            await self.bot.delete_message(chat_id, message_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
