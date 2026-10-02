from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    jwt_secret: str = Field(min_length=32)
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    timezone: str = "Asia/Tashkent"
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value):
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        ZoneInfo(value)
        return value


@lru_cache
def get_settings():
    return Settings()
