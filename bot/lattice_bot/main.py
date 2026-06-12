"""Discord bot entry point — DM listener that forwards to /api/chat.

Behavior per user direction (2G):
- Chat-first, no slash commands.
- DM-only. Channel messages are ignored.
- Only `DISCORD_OWNER_ID` is allowed; messages from any other user are
  silently dropped (single-user app).
- Session id is regenerated after `chat_session_idle_minutes` of silence
  (mirrors the backend's idle reset; both sides can converge).

Starts cleanly even when DISCORD_BOT_TOKEN is unset — prints a message and
exits 0 so the start.bat journey doesn't crash for users not yet using
Discord.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

import discord
import httpx

from lattice_bot.backend_client import BackendError, make_client, post_chat
from lattice_bot.config import LOGS_DIR, settings
from lattice_bot.formatters import split_for_discord

logger = logging.getLogger(__name__)

SESSION_IDLE_MINUTES = 30

# Discord markdown chars that would otherwise mangle a label (underscores
# trigger italics) when rendered inside the italic actions line.
_MD_SPECIALS = ("\\", "_", "*", "`", "~", "|")

# Human-friendly labels for the backend's write-tool names (see WRITE_TOOLS in
# backend/lattice/llm/router.py). Keeps the actions line readable and uniform.
_ACTION_LABELS = {
    "log_entry": "entry logged",
    "delete_entry": "entry deleted",
    "patch_entry": "entry updated",
    "check_habit": "habit check-in",
    "create_calendar_event": "calendar event created",
    "patch_calendar_event": "calendar event updated",
    "delete_calendar_event": "calendar event deleted",
    "sync_garmin": "garmin sync",
    "sync_calendar": "calendar sync",
    "save_plan": "plan saved",
    "save_research_paper": "research paper saved",
    "set_nutrition_goals": "nutrition goals set",
    "remember": "memory saved",
    "update_memory": "memory updated",
    "forget": "memory removed",
    "render_chart": "chart added",
    "update_dashboard_card": "chart updated",
    "delete_dashboard_card": "chart removed",
}


def _escape_md(text: str) -> str:
    """Backslash-escape Discord markdown so a label renders literally."""
    for ch in _MD_SPECIALS:
        text = text.replace(ch, "\\" + ch)
    return text


def _action_label(name: str) -> str:
    """Friendly label for a tool name; unknown names fall back to spaced text."""
    return _ACTION_LABELS.get(name, name.replace("_", " "))


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(logging.INFO)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
        file_handler = RotatingFileHandler(
            LOGS_DIR / "bot.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)


class LatticeBot(discord.Client):
    """Single-user DM bot — forwards messages to /api/chat."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.http_client: httpx.AsyncClient | None = None
        self._session_id: str = uuid.uuid4().hex
        self._last_activity_ts: float = 0.0
        self._owner_id: int | None = self._parse_owner_id()

    @staticmethod
    def _parse_owner_id() -> int | None:
        raw = settings.discord_owner_id
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.warning("DISCORD_OWNER_ID is not an integer: %r", raw)
            return None

    def _rotate_session_if_idle(self) -> None:
        now = time.monotonic()
        if (
            self._last_activity_ts
            and (now - self._last_activity_ts) > SESSION_IDLE_MINUTES * 60
        ):
            self._session_id = uuid.uuid4().hex
            logger.info("rotated session_id after idle window")
        self._last_activity_ts = now

    async def setup_hook(self) -> None:
        self.http_client = make_client()

    async def close(self) -> None:
        if self.http_client is not None:
            await self.http_client.aclose()
        await super().close()

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info(
            "logged in as %s (id=%s); owner=%s; backend=%s",
            self.user, self.user.id, self._owner_id, settings.backend_url,
        )

    async def on_message(self, message: discord.Message) -> None:
        # Ignore self.
        if message.author.id == (self.user.id if self.user else -1):
            return
        # DM only.
        if not isinstance(message.channel, discord.DMChannel):
            return
        # Single user gate.
        if self._owner_id is not None and message.author.id != self._owner_id:
            logger.info(
                "ignored DM from non-owner %s (%s)",
                message.author, message.author.id,
            )
            return

        content = (message.content or "").strip()
        if not content:
            return

        self._rotate_session_if_idle()
        logger.info(
            "[%s] %s: %s",
            datetime.now(UTC).isoformat(timespec="seconds"),
            message.author,
            content[:120],
        )

        if self.http_client is None:
            await message.channel.send("Backend client not initialized.")
            return

        try:
            async with message.channel.typing():
                reply = await post_chat(
                    self.http_client,
                    session_id=self._session_id,
                    message=content,
                )
        except BackendError as exc:
            await self._send_chunks(
                message.channel, f"⚠ backend error {exc.status_code}: {exc.detail}",
            )
            return
        except httpx.TimeoutException:
            await message.channel.send("Backend timed out. Try again.")
            return
        except httpx.HTTPError as exc:
            await message.channel.send(f"Network error: {exc}")
            return

        text = reply.reply or "(empty response)"
        if reply.actions_taken:
            counts: dict[str, int] = {}
            for action in reply.actions_taken:
                counts[action] = counts.get(action, 0) + 1
            summary = ", ".join(
                f"{_escape_md(_action_label(name))} ×{n}"
                if n > 1
                else _escape_md(_action_label(name))
                for name, n in counts.items()
            )
            text += "\n\n_actions: " + summary + "_"
        await self._send_chunks(message.channel, text)

    @staticmethod
    async def _send_chunks(channel: discord.abc.Messageable, text: str) -> None:
        for chunk in split_for_discord(text):
            await channel.send(chunk)


async def _async_main() -> int:
    _setup_logging()
    token = settings.discord_bot_token
    if not token:
        sys.stdout.write(
            "Lattice bot — DISCORD_BOT_TOKEN not set, nothing to do.\n"
            "Configure it in .env to enable the Discord chat agent.\n",
        )
        return 0
    if not settings.bot_shared_secret:
        logger.warning(
            "BOT_SHARED_SECRET not set — backend will accept the bot only "
            "while running in dev-permissive mode (no WEB_UI_PASSWORD).",
        )
    bot = LatticeBot()
    try:
        await bot.start(token)
    except discord.LoginFailure as exc:
        logger.error("Discord login failed: %s", exc)
        return 1
    except KeyboardInterrupt:
        pass
    finally:
        if not bot.is_closed():
            await bot.close()
    return 0


def main() -> int:
    try:
        return asyncio.run(_async_main())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
