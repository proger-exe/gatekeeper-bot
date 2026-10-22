from __future__ import annotations

from datetime import timedelta

from sqlalchemy import String, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sub_bot.storage.models import (
    AuditLog,
    CleanupTask,
    ProtectedChat,
    RequiredTarget,
    ScheduledUnmuteTask,
    UserAccessState,
    UserViolation,
    WhitelistUser,
)
from sub_bot.time_utils import utc_now


class ChatRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_chat_id(self, chat_id: int) -> ProtectedChat | None:
        result = await self.session.execute(select(ProtectedChat).where(ProtectedChat.chat_id == chat_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, protected_chat_id: int) -> ProtectedChat | None:
        result = await self.session.execute(select(ProtectedChat).where(ProtectedChat.id == protected_chat_id))
        return result.scalar_one_or_none()

    async def create_or_update_chat(
        self,
        chat_id: int,
        title: str | None,
        notification_ttl_sec: int,
        notification_cooldown_sec: int,
        subscription_cache_ttl_sec: int,
        mute_window_sec: int,
        mute_step_seconds: list[int],
    ) -> ProtectedChat:
        chat = await self.get_by_chat_id(chat_id)
        if chat is None:
            chat = ProtectedChat(
                chat_id=chat_id,
                title=title,
                notification_ttl_sec=notification_ttl_sec,
                notification_cooldown_sec=notification_cooldown_sec,
                subscription_cache_ttl_sec=subscription_cache_ttl_sec,
                mute_window_sec=mute_window_sec,
                mute_step_seconds=mute_step_seconds,
            )
            self.session.add(chat)
            await self.session.flush()
            return chat

        chat.title = title
        return chat

    async def add_target(self, protected_chat_id: int, chat_id: int | None, username: str | None, title: str | None, target_type: str) -> RequiredTarget:
        existing = await self.session.execute(
            select(RequiredTarget).where(
                RequiredTarget.protected_chat_id == protected_chat_id,
                RequiredTarget.target_chat_id == chat_id,
            )
        )
        target = existing.scalar_one_or_none()
        if target is None:
            target = RequiredTarget(
                protected_chat_id=protected_chat_id,
                target_chat_id=chat_id,
                target_username=username,
                target_title=title,
                target_type=target_type,
            )
            self.session.add(target)
            await self.session.flush()
            return target

        target.target_username = username
        target.target_title = title
        target.target_type = target_type
        target.is_active = True
        target.is_valid = True
        return target

    async def deactivate_target(self, protected_chat_id: int, raw_target: str) -> bool:
        stmt = select(RequiredTarget).where(
            RequiredTarget.protected_chat_id == protected_chat_id,
            (RequiredTarget.target_username == raw_target.lstrip("@")) | (func.cast(RequiredTarget.target_chat_id, String) == raw_target)
        )
        result = await self.session.execute(stmt)
        target = result.scalar_one_or_none()
        if target is None:
            return False
        target.is_active = False
        return True

    async def list_targets(self, protected_chat_id: int) -> list[RequiredTarget]:
        result = await self.session.execute(
            select(RequiredTarget)
            .where(RequiredTarget.protected_chat_id == protected_chat_id)
            .order_by(RequiredTarget.sort_order.asc(), RequiredTarget.id.asc())
        )
        return list(result.scalars().all())

    async def get_or_create_state(self, protected_chat_id: int, user_id: int) -> UserAccessState:
        result = await self.session.execute(
            select(UserAccessState).where(
                UserAccessState.protected_chat_id == protected_chat_id, UserAccessState.user_id == user_id
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = UserAccessState(protected_chat_id=protected_chat_id, user_id=user_id)
            self.session.add(state)
            await self.session.flush()
        return state

    async def get_recent_subscription_state(
        self,
        protected_chat_id: int,
        user_id: int,
        max_age_seconds: int,
    ) -> UserAccessState | None:
        cutoff = utc_now() - timedelta(seconds=max_age_seconds)
        result = await self.session.execute(
            select(UserAccessState).where(
                UserAccessState.protected_chat_id == protected_chat_id,
                UserAccessState.user_id == user_id,
                UserAccessState.last_checked_at.is_not(None),
                UserAccessState.last_checked_at >= cutoff,
            )
        )
        return result.scalar_one_or_none()

    async def is_whitelisted(self, protected_chat_id: int, user_id: int) -> bool:
        result = await self.session.execute(
            select(WhitelistUser.id).where(
                WhitelistUser.protected_chat_id == protected_chat_id, WhitelistUser.user_id == user_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_whitelist(self, protected_chat_id: int, user_id: int) -> None:
        if not await self.is_whitelisted(protected_chat_id, user_id):
            self.session.add(WhitelistUser(protected_chat_id=protected_chat_id, user_id=user_id))

    async def remove_whitelist(self, protected_chat_id: int, user_id: int) -> bool:
        result = await self.session.execute(
            delete(WhitelistUser).where(
                WhitelistUser.protected_chat_id == protected_chat_id, WhitelistUser.user_id == user_id
            )
        )
        return result.rowcount > 0

    async def append_audit(self, protected_chat_id: int, user_id: int | None, event_type: str, payload_json: dict) -> None:
        self.session.add(
            AuditLog(
                protected_chat_id=protected_chat_id,
                user_id=user_id,
                event_type=event_type,
                payload_json=payload_json,
            )
        )

    async def add_violation(self, protected_chat_id: int, user_id: int, reason: str) -> None:
        self.session.add(UserViolation(protected_chat_id=protected_chat_id, user_id=user_id, reason=reason))

    async def count_recent_violations(
        self,
        protected_chat_id: int,
        user_id: int,
        reason: str,
        window_seconds: int,
    ) -> int:
        since = utc_now() - timedelta(seconds=window_seconds)
        result = await self.session.execute(
            select(func.count(UserViolation.id)).where(
                UserViolation.protected_chat_id == protected_chat_id,
                UserViolation.user_id == user_id,
                UserViolation.reason == reason,
                UserViolation.created_at >= since,
            )
        )
        return int(result.scalar_one())

    async def aggregate_stats(self, protected_chat_id: int, hours: int = 24) -> dict[str, int]:
        since = utc_now() - timedelta(hours=hours)
        result = await self.session.execute(
            select(AuditLog.event_type, func.count(AuditLog.id))
            .where(AuditLog.protected_chat_id == protected_chat_id, AuditLog.created_at >= since)
            .group_by(AuditLog.event_type)
        )
        return {event_type: count for event_type, count in result.all()}

    async def enqueue_cleanup(self, chat_id: int, message_id: int, delay_seconds: int) -> None:
        self.session.add(
            CleanupTask(
                chat_id=chat_id,
                message_id=message_id,
                delete_after=utc_now() + timedelta(seconds=delay_seconds),
            )
        )

    async def fetch_due_cleanup_tasks(self, limit: int = 100) -> list[CleanupTask]:
        result = await self.session.execute(
            select(CleanupTask)
            .where(CleanupTask.delete_after <= utc_now())
            .order_by(CleanupTask.delete_after.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_cleanup_task(self, task_id: int) -> None:
        await self.session.execute(delete(CleanupTask).where(CleanupTask.id == task_id))

    async def schedule_unmute(self, protected_chat_id: int, chat_id: int, user_id: int, delay_seconds: int) -> None:
        result = await self.session.execute(
            select(ScheduledUnmuteTask).where(
                ScheduledUnmuteTask.protected_chat_id == protected_chat_id,
                ScheduledUnmuteTask.user_id == user_id,
            )
        )
        task = result.scalar_one_or_none()
        unmute_after = utc_now() + timedelta(seconds=delay_seconds)
        if task is None:
            self.session.add(
                ScheduledUnmuteTask(
                    protected_chat_id=protected_chat_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    unmute_after=unmute_after,
                )
            )
            return

        task.chat_id = chat_id
        task.unmute_after = unmute_after

    async def fetch_due_unmute_tasks(self, limit: int = 100) -> list[ScheduledUnmuteTask]:
        result = await self.session.execute(
            select(ScheduledUnmuteTask)
            .where(ScheduledUnmuteTask.unmute_after <= utc_now())
            .order_by(ScheduledUnmuteTask.unmute_after.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete_unmute_task(self, task_id: int) -> None:
        await self.session.execute(delete(ScheduledUnmuteTask).where(ScheduledUnmuteTask.id == task_id))

    async def delete_user_unmute_task(self, protected_chat_id: int, user_id: int) -> None:
        await self.session.execute(
            delete(ScheduledUnmuteTask).where(
                ScheduledUnmuteTask.protected_chat_id == protected_chat_id,
                ScheduledUnmuteTask.user_id == user_id,
            )
        )
