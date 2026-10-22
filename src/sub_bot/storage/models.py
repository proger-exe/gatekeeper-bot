from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ProtectedChat(Base):
    __tablename__ = "protected_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notification_ttl_sec: Mapped[int] = mapped_column(Integer, default=60)
    notification_cooldown_sec: Mapped[int] = mapped_column(Integer, default=300)
    subscription_cache_ttl_sec: Mapped[int] = mapped_column(Integer, default=300)
    mute_window_sec: Mapped[int] = mapped_column(Integer, default=60)
    mute_step_seconds: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )

    required_targets: Mapped[list[RequiredTarget]] = relationship(back_populates="protected_chat", lazy="selectin")


class RequiredTarget(Base):
    __tablename__ = "required_targets"
    __table_args__ = (UniqueConstraint("protected_chat_id", "target_chat_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    target_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_type: Mapped[str] = mapped_column(String(32), default="unknown")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    protected_chat: Mapped[ProtectedChat] = relationship(back_populates="required_targets")


class UserAccessState(Base):
    __tablename__ = "user_access_state"
    __table_args__ = (UniqueConstraint("protected_chat_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    last_subscription_status: Mapped[str] = mapped_column(String(16), default="unknown")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    is_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_notice_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    last_notice_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_penalty_level: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
    )


class WhitelistUser(Base):
    __tablename__ = "whitelist_users"
    __table_args__ = (UniqueConstraint("protected_chat_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())


class UserViolation(Base):
    __tablename__ = "user_violations"

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    reason: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), index=True)


class CleanupTask(Base):
    __tablename__ = "cleanup_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    delete_after: Mapped[datetime] = mapped_column(DateTime(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())


class ScheduledUnmuteTask(Base):
    __tablename__ = "scheduled_unmute_tasks"
    __table_args__ = (UniqueConstraint("protected_chat_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    protected_chat_id: Mapped[int] = mapped_column(ForeignKey("protected_chats.id", ondelete="CASCADE"))
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    unmute_after: Mapped[datetime] = mapped_column(DateTime(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
