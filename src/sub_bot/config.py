from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    admin_user_ids_raw: str = Field(default="", alias="ADMIN_USER_IDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    default_notification_ttl_sec: int = Field(default=60, alias="DEFAULT_NOTIFICATION_TTL_SEC")
    default_notification_cooldown_sec: int = Field(default=300, alias="DEFAULT_NOTIFICATION_COOLDOWN_SEC")
    default_subscription_cache_ttl_sec: int = Field(default=300, alias="DEFAULT_SUBSCRIPTION_CACHE_TTL_SEC")
    default_mute_window_sec: int = Field(default=60, alias="DEFAULT_MUTE_WINDOW_SEC")
    default_mute_steps: str = Field(default="60", alias="DEFAULT_MUTE_STEPS")

    @property
    def mute_steps(self) -> list[int]:
        return [int(item.strip()) for item in self.default_mute_steps.split(",") if item.strip()]

    @property
    def admin_user_ids(self) -> set[int]:
        return {int(item.strip()) for item in self.admin_user_ids_raw.split(",") if item.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
