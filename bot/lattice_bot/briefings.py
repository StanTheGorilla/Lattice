"""Morning + evening briefings (SPEC §8.4, §9).

Two scheduled DMs:
  07:30  Morning brief — readiness, last-night sleep, top work window, training rec,
                         first event of the day.
  21:00  Evening brief  — today's logged entries summary, sleep window for tonight,
                         caffeine last-call, habits missing for today.

Deterministic templates (decision 2I-1). Pull from backend endpoints, format,
DM the owner. No LLM tokens spent.

The schedule lives inside the bot process (per SPEC §8.4 "APScheduler in the
bot"). Backend's scheduler handles its own jobs (garmin/readiness/weekly
report); these two are user-facing pushes that belong with the user-facing
process.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import discord
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from lattice_bot.backend_client import BackendError, get_json, post_chat
from lattice_bot.config import settings

logger = logging.getLogger(__name__)

MORNING_HOUR, MORNING_MIN = 7, 30
DAY_REVIEW_HOUR, DAY_REVIEW_MIN = 20, 0
EVENING_HOUR, EVENING_MIN = 21, 0


# --------------------------------------------------------------------------- #
# Formatters (pure, easy to test)
# --------------------------------------------------------------------------- #


def _fmt_duration_min(mins: float | int | None) -> str:
    if mins is None:
        return "—"
    h, m = divmod(int(mins), 60)
    return f"{h}h {m:02d}m"


def _local_clock(iso: str | None, tz: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    return dt.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def format_morning(
    *,
    readiness: dict[str, Any],
    sleep_window: dict[str, Any],
    training: dict[str, Any],
    work_windows: dict[str, Any],
    calendar_events: list[dict[str, Any]],
    tz: str,
) -> str:
    """Build the deterministic morning-brief body."""
    lines: list[str] = [f"**☀  Morning brief — {datetime.now(ZoneInfo(tz)).strftime('%a %d %b')}**"]
    score = readiness.get("score")
    cat = readiness.get("category")
    if score is not None:
        provisional = " (provisional)" if readiness.get("provisional") else ""
        lines.append(f"Readiness: **{score}** ({cat}){provisional}")
    else:
        lines.append("Readiness: —")
    # Last-night sleep is recorded as today's sleep_score; we pulled it via /metrics
    # but here we just use sleep_window inputs.
    inputs = sleep_window.get("inputs", {}) if sleep_window else {}
    sleep_score = inputs.get("sleep_score_today")
    sleep_dur = inputs.get("sleep_duration_min_today")
    if sleep_score or sleep_dur:
        lines.append(f"Sleep last night: {_fmt_duration_min(sleep_dur)}, score {sleep_score or '—'}")
    # Top work window
    windows = work_windows.get("windows", []) if work_windows else []
    if windows:
        top = windows[0]
        lines.append(
            f"Top window: {_local_clock(top.get('start'), tz)}–"
            f"{_local_clock(top.get('end'), tz)} "
            f"(predicted focus {top.get('predicted_focus')})",
        )
    else:
        lines.append("Top window: no 60-min gap today")
    # Training
    if training:
        rec = training.get("recommendation")
        rationale = "; ".join((training.get("rationale") or [])[:1]) or ""
        lines.append(f"Train: **{rec}** {f'— {rationale}' if rationale else ''}")
    # First event today
    first = None
    today_start = datetime.now(ZoneInfo(tz)).replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    for ev in calendar_events:
        try:
            s = datetime.fromisoformat(ev["start"])
        except (KeyError, ValueError):
            continue
        if s.tzinfo is None:
            s = s.replace(tzinfo=ZoneInfo(tz))
        s_local = s.astimezone(ZoneInfo(tz))
        if today_start <= s_local < today_end and not ev.get("is_all_day"):
            first = ev
            break
    if first:
        lines.append(
            f"First event: {_local_clock(first.get('start'), tz)} {first.get('title') or ''}",
        )
    else:
        lines.append("First event: none scheduled")
    return "\n".join(lines)


def format_evening(
    *,
    entries: dict[str, Any],
    sleep_window: dict[str, Any],
    caffeine: dict[str, Any],
    habits_adherence: dict[str, Any],
    tz: str,
) -> str:
    """Build the deterministic evening-brief body."""
    lines: list[str] = [f"**🌙  Evening brief — {datetime.now(ZoneInfo(tz)).strftime('%a %d %b')}**"]
    items = (entries or {}).get("items", [])
    # Group counts by type
    counts: dict[str, int] = {}
    for it in items:
        counts[it.get("type", "?")] = counts.get(it.get("type", "?"), 0) + 1
    if counts:
        counts_str = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        lines.append(f"Logged today: {counts_str}")
    else:
        lines.append("Logged today: nothing")
    # Sleep window for tonight
    if sleep_window:
        bedtime = _local_clock(sleep_window.get("bedtime"), tz)
        wake = _local_clock(sleep_window.get("wake_time"), tz)
        dur = _fmt_duration_min(sleep_window.get("target_duration_min"))
        lines.append(f"Sleep tonight: bed **{bedtime}** → wake {wake} ({dur})")
        for flag in (sleep_window.get("flags") or [])[:2]:
            lines.append(f"  • {flag}")
    # Caffeine
    if caffeine:
        residual = caffeine.get("residual_at_bedtime_mg")
        last_call = caffeine.get("last_call_minutes")
        safe = caffeine.get("safe_for_new_cup")
        if last_call is not None:
            lines.append(
                f"Caffeine: residual {residual:.0f}mg at bed; last call in {last_call} min",
            )
        else:
            verdict = "OK" if safe else "skip the cup"
            lines.append(f"Caffeine: residual {residual:.0f}mg at bed — {verdict}")
    # Habits missing today
    today_iso = datetime.now(ZoneInfo(tz)).date().isoformat()
    missing: list[str] = []
    for h in (habits_adherence or {}).get("items", []):
        if h.get("current_streak_days", 0) == 0 and h.get("target_per_week", 0) >= 5:
            missing.append(h.get("name", "?"))
    if missing:
        lines.append(f"Habits not yet checked today: {', '.join(missing)}")
    else:
        lines.append("Habits: all daily ones logged or n/a")
    lines.append(f"_({today_iso})_")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Briefing jobs (impure — they fetch + DM)
# --------------------------------------------------------------------------- #


def _today_window(tz: str) -> tuple[str, str]:
    zone = ZoneInfo(tz)
    start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


async def _safe_get(client: httpx.AsyncClient, path: str) -> Any:
    try:
        return await get_json(client, path)
    except BackendError as exc:
        logger.warning("brief fetch %s: backend %s: %s", path, exc.status_code, exc.detail)
    except httpx.HTTPError as exc:
        logger.warning("brief fetch %s: %s", path, exc)
    return None


async def run_morning_brief(
    client: httpx.AsyncClient,
    sender: "BriefSender",
) -> None:
    tz = settings.timezone
    today_start, today_end = _today_window(tz)
    readiness = await _safe_get(client, "/api/functions/readiness")
    sleep = await _safe_get(client, "/api/functions/sleep_window")
    training = await _safe_get(client, "/api/functions/training_recommendation")
    work_windows = await _safe_get(client, "/api/functions/work_windows?min_minutes=60")
    events = await _safe_get(client, f"/api/calendar/events?from={today_start}&to={today_end}") or []
    if all(x is None for x in (readiness, sleep, training, work_windows)):
        await sender.send("⚠ Morning brief: backend unreachable.")
        return
    body = format_morning(
        readiness=readiness or {},
        sleep_window=sleep or {},
        training=training or {},
        work_windows=work_windows or {},
        calendar_events=events or [],
        tz=tz,
    )
    await sender.send(body)


_DAY_REVIEW_SESSION = "system_day_review_{date}"

_DAY_REVIEW_PROMPT = (
    "Daily review time. Analyse today and give me two short sections:\n\n"
    "**Positives** — what went well today based on the data (metrics, habits, "
    "sleep, energy, training, or anything else relevant). Be specific with numbers.\n\n"
    "**Watch out for / avoid** — what the data suggests I should be careful about "
    "or avoid tomorrow. Reference active plans where relevant.\n\n"
    "Use tools to pull today's data first. Keep the whole reply under 300 words. "
    "No preamble, no sign-off."
)


async def run_day_review(
    client: httpx.AsyncClient,
    sender: "BriefSender",
) -> None:
    tz = settings.timezone
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    session_id = _DAY_REVIEW_SESSION.format(date=today)
    try:
        result = await post_chat(client, session_id=session_id, message=_DAY_REVIEW_PROMPT)
        await sender.send(result.reply)
    except BackendError as exc:
        logger.warning("day review backend error %s: %s", exc.status_code, exc.detail)
        await sender.send("⚠ Day review: backend error — check logs.")
    except httpx.HTTPError as exc:
        logger.warning("day review http error: %s", exc)
        await sender.send("⚠ Day review: connection error — check logs.")


async def run_evening_brief(
    client: httpx.AsyncClient,
    sender: "BriefSender",
) -> None:
    tz = settings.timezone
    today_start, today_end = _today_window(tz)
    entries = await _safe_get(
        client, f"/api/entries?from={today_start}&to={today_end}&limit=200",
    )
    sleep = await _safe_get(client, "/api/functions/sleep_window")
    caffeine = await _safe_get(client, "/api/functions/caffeine_status")
    habits = await _safe_get(client, "/api/functions/habits/adherence")
    if all(x is None for x in (entries, sleep, caffeine, habits)):
        await sender.send("⚠ Evening brief: backend unreachable.")
        return
    body = format_evening(
        entries=entries or {},
        sleep_window=sleep or {},
        caffeine=caffeine or {},
        habits_adherence=habits or {},
        tz=tz,
    )
    await sender.send(body)


# --------------------------------------------------------------------------- #
# DM sender + scheduler wiring
# --------------------------------------------------------------------------- #


class BriefSender:
    """Resolves the owner's DM channel lazily and sends one message."""

    def __init__(self, bot: discord.Client, owner_id: int) -> None:
        self.bot = bot
        self.owner_id = owner_id
        self._channel: discord.DMChannel | None = None

    async def _ensure_channel(self) -> discord.DMChannel | None:
        if self._channel is not None:
            return self._channel
        try:
            user = await self.bot.fetch_user(self.owner_id)
        except discord.NotFound:
            logger.error("owner_id %s not found on Discord", self.owner_id)
            return None
        self._channel = await user.create_dm()
        return self._channel

    async def send(self, text: str) -> None:
        channel = await self._ensure_channel()
        if channel is None:
            return
        # Discord 2000-char limit. Briefings should easily fit, but be safe.
        if len(text) > 1900:
            text = text[:1900] + "…"
        await channel.send(text)


def schedule(
    bot: discord.Client,
    *,
    http_client: httpx.AsyncClient,
    owner_id: int,
    tz: str,
) -> AsyncIOScheduler:
    """Start the briefings scheduler. Idempotent per process — call once."""
    sender = BriefSender(bot, owner_id)
    sched = AsyncIOScheduler(timezone=tz)

    async def morning() -> None:
        try:
            await run_morning_brief(http_client, sender)
        except Exception:  # noqa: BLE001
            logger.exception("morning brief crashed")

    async def day_review() -> None:
        try:
            await run_day_review(http_client, sender)
        except Exception:  # noqa: BLE001
            logger.exception("day review crashed")

    async def evening() -> None:
        try:
            await run_evening_brief(http_client, sender)
        except Exception:  # noqa: BLE001
            logger.exception("evening brief crashed")

    sched.add_job(
        morning,
        trigger=CronTrigger(hour=MORNING_HOUR, minute=MORNING_MIN),
        id="morning_brief",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        day_review,
        trigger=CronTrigger(hour=DAY_REVIEW_HOUR, minute=DAY_REVIEW_MIN),
        id="day_review",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        evening,
        trigger=CronTrigger(hour=EVENING_HOUR, minute=EVENING_MIN),
        id="evening_brief",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    logger.info(
        "briefings scheduled — morning %02d:%02d, day review %02d:%02d, "
        "evening %02d:%02d (tz=%s)",
        MORNING_HOUR, MORNING_MIN,
        DAY_REVIEW_HOUR, DAY_REVIEW_MIN,
        EVENING_HOUR, EVENING_MIN, tz,
    )
    return sched


__all__ = [
    "BriefSender",
    "format_evening",
    "format_morning",
    "run_day_review",
    "run_evening_brief",
    "run_morning_brief",
    "schedule",
]
