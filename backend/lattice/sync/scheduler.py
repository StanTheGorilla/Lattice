"""APScheduler setup (SPEC §9).

Jobs registered (all gated by LATTICE_DISABLE_SCHEDULER):
  - garmin_sync           : hourly @ :05 (2B)
  - readiness_compute     : daily @ 06:00 — persist today's F1 score (2I)
  - weekly_report         : Sunday @ 22:00 — generate F7 for the current ISO week (2I)
  - conversation_prune    : daily @ 03:00 — trim conversations older than 30 days (2J)
  - calendar_cache_prune  : hourly @ :15 — drop events ending >1 day ago (2J)

The scheduler is **disabled by default** in dev because `uvicorn --reload`
spawns duplicate processes that would each run jobs. Set
`LATTICE_DISABLE_SCHEDULER=false` for the prod-mode run.

Every job wraps its work in a broad try/except so a single bad day never
crashes the scheduler. Errors are logged with full context per SPEC §error
handling.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from lattice.config import settings
from lattice.db import SessionLocal
from lattice.functions.alert_checker import run_alert_check
from lattice.functions.readiness import compute_readiness
from lattice.functions.weekly_report import generate_weekly_report
from lattice.integrations.garmin import GarminAuthError, GarminUnavailable
from lattice.models import Conversation, Metric
from lattice.sync.calendar_sync import prune_old_events
from lattice.sync.garmin_sync import sync_recent

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _garmin_hourly_job() -> None:
    try:
        async with SessionLocal() as session:
            report = await sync_recent(session, days=1)
        logger.info(
            "garmin hourly sync: wrote %d rows for %s (errors=%d)",
            report.rows_written, report.dates, len(report.errors),
        )
    except GarminAuthError as exc:
        logger.error("garmin auth broken — pausing scheduler until next attempt: %s", exc)
    except GarminUnavailable as exc:
        logger.warning("garmin transient unavailable: %s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("garmin hourly sync crashed")


async def _readiness_compute_job() -> None:
    """Persist today's F1 score as a `readiness_score` metric row.

    Idempotent via UPSERT on (metric_name, timestamp, source). SPEC §6 F1
    flags `provisional` when baselines are sparse; we still persist it so
    weekly stats have a row, and the API can expose `provisional` separately.
    """
    try:
        tz = settings.timezone
        today = datetime.now(ZoneInfo(tz)).date()
        async with SessionLocal() as session:
            result = await compute_readiness(session, target=today, tz=tz)
            if result.score == 0 and not result.explanation.components:
                logger.info("readiness compute: no component data for %s — skip", today)
                return
            timestamp = datetime.combine(
                today, datetime.min.time(), tzinfo=ZoneInfo(tz),
            ).isoformat()
            stmt = sqlite_insert(Metric.__table__).values(
                timestamp=timestamp,
                metric_name="readiness_score",
                value=float(result.score),
                unit="score",
                source="derived",
                metadata=None,
            ).on_conflict_do_update(
                index_elements=["metric_name", "timestamp", "source"],
                set_={"value": float(result.score)},
            )
            await session.execute(stmt)
            await session.commit()
        logger.info("readiness compute: %s score=%d", today, result.score)
    except Exception:  # noqa: BLE001
        logger.exception("readiness compute crashed")


async def _conversation_prune_job() -> None:
    """Trim `conversations` rows older than 30 days (SPEC §4.4)."""
    try:
        cutoff = (datetime.now(ZoneInfo(settings.timezone)) - timedelta(days=30)).isoformat()
        async with SessionLocal() as session:
            result = await session.execute(
                delete(Conversation).where(Conversation.timestamp < cutoff),
            )
            await session.commit()
        logger.info("conversation prune: deleted %d rows older than %s", result.rowcount or 0, cutoff)
    except Exception:  # noqa: BLE001
        logger.exception("conversation prune crashed")


async def _calendar_cache_prune_job() -> None:
    """Drop calendar_cache rows whose events ended >1 day ago (SPEC §4.3)."""
    try:
        async with SessionLocal() as session:
            deleted = await prune_old_events(session, older_than_days=1)
        logger.info("calendar cache prune: deleted %d rows", deleted)
    except Exception:  # noqa: BLE001
        logger.exception("calendar cache prune crashed")


async def _alert_check_job() -> None:
    """Evaluate active threshold alert rules and fire Discord DMs if triggered."""
    try:
        async with SessionLocal() as session:
            fired = await run_alert_check(session)
        if fired:
            logger.info("alert check: %d alert(s) fired", fired)
    except Exception:  # noqa: BLE001
        logger.exception("alert check crashed")


async def _weekly_report_job() -> None:
    """Generate F7 for the ISO week containing *today*.

    Scheduled for Sun 22:00 (SPEC §9), so 'today' is Sunday and the ISO week
    is the Mon-Sun about to close. Stage B is best-effort: if DeepSeek is down,
    the row is persisted with a deterministic fallback (see weekly_report.py).
    """
    try:
        tz = settings.timezone
        today = datetime.now(ZoneInfo(tz)).date()
        async with SessionLocal() as session:
            row = await generate_weekly_report(session, target=today, tz=tz)
        logger.info(
            "weekly report generated: %s (model=%s, %d chars)",
            row.iso_week, row.model_used, len(row.summary_text),
        )
    except Exception:  # noqa: BLE001
        logger.exception("weekly report crashed")


def start() -> AsyncIOScheduler | None:
    global _scheduler
    if settings.lattice_disable_scheduler:
        logger.info("scheduler disabled (LATTICE_DISABLE_SCHEDULER=true)")
        return None
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone=settings.timezone)
    sched.add_job(
        _garmin_hourly_job,
        trigger=CronTrigger(minute=5),
        id="garmin_sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _readiness_compute_job,
        trigger=CronTrigger(hour=6, minute=0),
        id="readiness_compute",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _weekly_report_job,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=0),
        id="weekly_report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _conversation_prune_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="conversation_prune",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _calendar_cache_prune_job,
        trigger=CronTrigger(minute=15),
        id="calendar_cache_prune",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _alert_check_job,
        trigger=CronTrigger(minute=30),
        id="alert_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    logger.info(
        "scheduler started (tz=%s) — jobs: garmin_sync, readiness_compute, weekly_report, "
        "conversation_prune, calendar_cache_prune, alert_check",
        settings.timezone,
    )
    return sched


def shutdown() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("scheduler stopped")


__all__ = ["shutdown", "start"]
