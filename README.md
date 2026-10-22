# GateKeeper (sub-bot)

<!-- portfolio-card:start -->
[![sh3lby.code — нейтральная обложка](docs/portfolio/card.png)](docs/portfolio/card.svg)
<!-- portfolio-card:end -->

MVP Telegram-бот для публичного чата: проверяет обязательные подписки, ограничивает право писать, удаляет сообщения нарушителей, дедуплицирует уведомления и выдаёт муты.

## Запуск

1. Создай `.env` на основе `.env.example`.
2. Установи зависимости: `python -m venv .venv && . .venv/bin/activate && pip install -e .`
3. Заполни `ADMIN_USER_IDS` списком `user_id`, которым разрешено управление ботом.
4. Запусти бота: `sub-bot`

## Команды

- `/help`
- `/setup`
- `/required_add [chat_id] [@username]`
- `/required_remove [chat_id|@username]`
- `/required_list`
- `/ttl [seconds]`
- `/cooldown [seconds]`
- `/mute_policy`
- `/whitelist_add [user_id]`
- `/whitelist_remove [user_id]`
- `/status`
- `/stats`

## Ограничения MVP

- Бот должен быть админом в защищаемом чате.
- Управление доступно только `user_id` из `ADMIN_USER_IDS`, а не всем админам Telegram-чата.
- Бот должен быть добавлен в обязательные каналы/чаты, чтобы проверять membership.
- Кнопки проверки работают прямо в групповом сервисном сообщении.
- Временный мут снимается локальным воркером бота примерно через 1 минуту.
