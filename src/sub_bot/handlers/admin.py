from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sub_bot.config import Settings
from sub_bot.storage.db import session_scope
from sub_bot.storage.models import ProtectedChat
from sub_bot.storage.repositories import ChatRepository

router = Router()

HELP_TEXT = (
    "Команды бота:\n"
    "/help - показать эту справку\n"
    "/setup - подключить текущий чат\n"
    "/required_add [chat_id] [@username] - добавить обязательный канал/чат\n"
    "/required_remove [chat_id|@username] - отключить обязательную цель\n"
    "/required_list - показать обязательные цели\n"
    "/ttl [seconds] - TTL удаления сервисных сообщений\n"
    "/cooldown [seconds] - cooldown повторных уведомлений\n"
    "/mute_policy - показать политику временных ограничений\n"
    "/whitelist_add [user_id] - добавить пользователя в whitelist\n"
    "/whitelist_remove [user_id] - удалить пользователя из whitelist\n"
    "/status - показать состояние конфигурации\n"
    "/stats - показать базовую статистику"
)


async def _require_config_admin(message: Message, settings: Settings) -> bool:
    if message.from_user is None:
        return False
    return message.from_user.id in settings.admin_user_ids


async def _get_protected_chat(session_factory: async_sessionmaker[AsyncSession], chat_id: int) -> ProtectedChat | None:
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        return await repo.get_by_chat_id(chat_id)


@router.message(Command("help"))
async def help_command(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    await message.reply(HELP_TEXT)


@router.message(Command("setup"))
async def setup_chat(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        chat = await repo.create_or_update_chat(
            chat_id=message.chat.id,
            title=message.chat.title,
            notification_ttl_sec=settings.default_notification_ttl_sec,
            notification_cooldown_sec=settings.default_notification_cooldown_sec,
            subscription_cache_ttl_sec=settings.default_subscription_cache_ttl_sec,
            mute_window_sec=settings.default_mute_window_sec,
            mute_step_seconds=settings.mute_steps,
        )
        await repo.append_audit(chat.id, message.from_user.id if message.from_user else None, "chat_setup", {})
    await message.reply("Чат подключён и готов к настройке обязательных подписок.")


@router.message(Command("required_add"))
async def required_add(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.reply("Использование: /required_add [chat_id] [@username]")
        return

    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return

    raw_chat_id = parts[1].strip()
    raw_username = parts[2].strip()
    if not raw_chat_id.lstrip("-").isdigit() or not raw_username.startswith("@"):
        await message.reply("Использование: /required_add [chat_id] [@username]")
        return

    target_chat_id = int(raw_chat_id)
    target_username = raw_username.lstrip("@")
    chat = await bot.get_chat(target_chat_id)
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        await repo.add_target(
            protected_chat.id,
            chat.id,
            target_username,
            chat.title,
            getattr(chat, "type", "unknown"),
        )
        await repo.append_audit(
            protected_chat.id,
            message.from_user.id if message.from_user else None,
            "required_added",
            {"target_chat_id": target_chat_id, "target_username": target_username},
        )
    await message.reply(f"Обязательная цель добавлена: {chat.title or target_username}")


@router.message(Command("required_remove"))
async def required_remove(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.reply("Использование: /required_remove [chat_id|@username]")
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        removed = await repo.deactivate_target(protected_chat.id, parts[1].strip())
    await message.reply("Цель отключена." if removed else "Цель не найдена.")


@router.message(Command("required_list"))
async def required_list(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        targets = await repo.list_targets(protected_chat.id)
    lines = []
    for target in targets:
        status = "active" if target.is_active else "disabled"
        validity = "valid" if target.is_valid else "invalid"
        label = target.target_title or target.target_username or str(target.target_chat_id)
        lines.append(
            f"• {label} | id={target.target_chat_id} | username=@{target.target_username or '-'} [{status}, {validity}]"
        )
    await message.reply("\n".join(lines) if lines else "Список обязательных целей пуст.")


@router.message(Command("ttl"))
async def ttl_update(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    await _update_int_setting(message, bot, session_factory, settings, "notification_ttl_sec", "TTL уведомлений обновлён.")


@router.message(Command("cooldown"))
async def cooldown_update(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    await _update_int_setting(message, bot, session_factory, settings, "notification_cooldown_sec", "Cooldown уведомлений обновлён.")


async def _update_int_setting(
    message: Message,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    field_name: str,
    success_text: str,
) -> None:
    if not await _require_config_admin(message, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Нужно передать целое число секунд.")
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        chat = await repo.get_by_chat_id(message.chat.id)
        setattr(chat, field_name, int(parts[1]))
    await message.reply(success_text)


@router.message(Command("mute_policy"))
async def mute_policy(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    mute_seconds = protected_chat.mute_step_seconds[0] if protected_chat.mute_step_seconds else 60
    await message.reply(
        f"Окно нарушений: {protected_chat.mute_window_sec}s\n"
        f"Временное ограничение на отправку сообщений: {mute_seconds}s через Telegram until_date"
    )


@router.message(Command("whitelist_add"))
async def whitelist_add(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    await _whitelist_change(message, bot, session_factory, settings, remove=False)


@router.message(Command("whitelist_remove"))
async def whitelist_remove(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    await _whitelist_change(message, bot, session_factory, settings, remove=True)


async def _whitelist_change(
    message: Message,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    remove: bool,
) -> None:
    if not await _require_config_admin(message, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Использование: /whitelist_add [user_id]")
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    user_id = int(parts[1])
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        if remove:
            changed = await repo.remove_whitelist(protected_chat.id, user_id)
        else:
            await repo.add_whitelist(protected_chat.id, user_id)
            changed = True
    await message.reply("Whitelist обновлён." if changed else "Пользователь не найден в whitelist.")


@router.message(Command("status"))
async def status(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    me = await bot.get_me()
    member = await bot.get_chat_member(message.chat.id, me.id)
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        targets = await repo.list_targets(protected_chat.id)
    target_lines = [
        f"• {(target.target_title or target.target_username or target.target_chat_id)}: {'ok' if target.is_valid else 'invalid'}"
        for target in targets
    ]
    targets_text = "\n".join(target_lines) if target_lines else "нет"
    text = (
        f"Бот: @{me.username}\n"
        f"Права в чате: {member.status}\n"
        f"TTL: {protected_chat.notification_ttl_sec}s\n"
        f"Cooldown: {protected_chat.notification_cooldown_sec}s\n"
        f"Cache TTL: {protected_chat.subscription_cache_ttl_sec}s\n"
        f"Обязательные цели:\n{targets_text}"
    )
    await message.reply(text)


@router.message(Command("stats"))
async def stats(message: Message, bot: Bot, session_factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    if not await _require_config_admin(message, settings):
        return
    protected_chat = await _get_protected_chat(session_factory, message.chat.id)
    if protected_chat is None:
        await message.reply("Сначала выполни /setup")
        return
    async with session_scope(session_factory) as session:
        repo = ChatRepository(session)
        stats_map = await repo.aggregate_stats(protected_chat.id)
    lines = [f"• {key}: {value}" for key, value in sorted(stats_map.items())]
    await message.reply("\n".join(lines) if lines else "Пока нет данных.")
