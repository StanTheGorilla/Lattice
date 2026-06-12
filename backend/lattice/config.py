"""Application configuration via pydantic-settings."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
LOGS_DIR = REPO_ROOT / "logs"


class Settings(BaseSettings):
    """All environment-backed settings.

    Values not yet wired (phases 2B onward) are optional and default to None.
    """

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # general
    timezone: str = Field(default="Europe/Warsaw", alias="TIMEZONE")
    lattice_disable_scheduler: bool = Field(default=True, alias="LATTICE_DISABLE_SCHEDULER")

    # auth
    web_ui_password: str | None = Field(default=None, alias="WEB_UI_PASSWORD")
    bot_shared_secret: str | None = Field(default=None, alias="BOT_SHARED_SECRET")

    # garmin (2B)
    garmin_email: str | None = Field(default=None, alias="GARMIN_EMAIL")
    garmin_password: str | None = Field(default=None, alias="GARMIN_PASSWORD")

    # google calendar (2C)
    google_oauth_client_id: str | None = Field(default=None, alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str | None = Field(
        default=None, alias="GOOGLE_OAUTH_CLIENT_SECRET"
    )

    # discord (2G)
    discord_bot_token: str | None = Field(default=None, alias="DISCORD_BOT_TOKEN")
    discord_owner_id: str | None = Field(default=None, alias="DISCORD_OWNER_ID")

    # deepseek (2G chat agent)
    deepseek_api_key: str | None = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model_default: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL_DEFAULT")
    deepseek_model_reasoner: str = Field(default="deepseek-reasoner", alias="DEEPSEEK_MODEL_REASONER")
    deepseek_timeout_s: float = Field(default=180.0, alias="LATTICE_DEEPSEEK_TIMEOUT_S")
    user_name: str = Field(default="Stan", alias="LATTICE_USER_NAME")
    chat_max_iterations: int = Field(default=25, alias="LATTICE_CHAT_MAX_ITERATIONS")
    # Max prior conversation MESSAGES (rows) replayed to the model per turn.
    # One exchange = 2 messages (user + assistant), so 20 ≈ the last 10 exchanges.
    # Older context is dropped on purpose; durable facts live in user_memory instead.
    chat_history_turns: int = Field(default=20, alias="LATTICE_CHAT_HISTORY_TURNS")
    chat_session_idle_minutes: int = Field(default=30, alias="LATTICE_CHAT_SESSION_IDLE_MIN")
    daily_token_budget_input: int = Field(default=1_000_000_000, alias="LATTICE_DAILY_TOKEN_BUDGET_INPUT")
    daily_token_budget_output: int = Field(default=1_000_000_000, alias="LATTICE_DAILY_TOKEN_BUDGET_OUTPUT")

    # research agent
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    research_dir: str = Field(default="data/research", alias="LATTICE_RESEARCH_DIR")

    @property
    def frontend_dist(self) -> Path:
        """Static SvelteKit build dir, served by FastAPI in production."""
        return REPO_ROOT / "frontend" / "build"

    @property
    def database_url(self) -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = DATA_DIR / "lattice.db"
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"

    @property
    def sync_database_url(self) -> str:
        """Sync URL used by Alembic migrations."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_path = DATA_DIR / "lattice.db"
        return f"sqlite:///{db_path.as_posix()}"


settings = Settings()


def configure_logging() -> None:
    """Configure root logger with a console handler and a rotating file handler."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)

    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOGS_DIR / "backend.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
