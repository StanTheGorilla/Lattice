"""Bot configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = REPO_ROOT / "logs"


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    discord_bot_token: str | None = Field(default=None, alias="DISCORD_BOT_TOKEN")
    discord_owner_id: str | None = Field(default=None, alias="DISCORD_OWNER_ID")
    bot_shared_secret: str | None = Field(default=None, alias="BOT_SHARED_SECRET")
    backend_url: str = Field(default="http://localhost:8000", alias="BACKEND_URL")
    timezone: str = Field(default="Europe/Warsaw", alias="TIMEZONE")


settings = BotSettings()
