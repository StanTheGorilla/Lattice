"""Garmin data freshness — surface stale data clearly to the LLM and user.

The Garmin watch only reaches our backend after it syncs to Garmin Connect
(via the phone app). If the user hasn't opened Garmin Connect since waking
up, our hourly sync pulls nothing new — and any "what about today's sleep?"
question will silently land on data that's days old.

This function compares "what would last night's row look like" against what
we actually have, and returns an advisory the LLM can echo to the user.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric, MetricSample

# Intra-day samples arrive every 2-3 minutes while worn; >6h with no new
# sample means the watch is no longer streaming to Garmin Connect.
SAMPLE_STALE_HOURS = 6.0

# Daily aggregates land once per night; >36h with no fresh aggregate means
# at least one whole night is missing.
DAILY_SEVERE_STALE_HOURS = 36.0


async def get_data_freshness(session: AsyncSession) -> dict[str, Any]:
    """Report on Garmin sync freshness.

    Returns:
      - latest_sleep_wake_date, sleep_nights_behind: do we have last night?
      - latest_metric_at + hours_since_latest_metric: any daily row at all?
      - latest_sample_at + hours_since_latest_sample: watch still streaming?
      - status: fresh | stale_today | stale_intraday | stale_severe
      - advisory: human-readable string the LLM should surface verbatim when
        relevant ("watch likely hasn't synced — open Garmin Connect").
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    now = datetime.now(zone)
    today = now.date()

    # Most recent sleep_score row — its anchor IS the wake date.
    latest_sleep_iso = (
        await session.execute(
            select(func.max(Metric.timestamp))
            .where(Metric.metric_name == "sleep_score"),
        )
    ).scalar_one_or_none()

    latest_sleep_wake_date: str | None = None
    sleep_nights_behind: int | None = None
    if latest_sleep_iso:
        try:
            wake_d = datetime.fromisoformat(latest_sleep_iso).astimezone(zone).date()
            latest_sleep_wake_date = wake_d.isoformat()
            sleep_nights_behind = (today - wake_d).days
        except (TypeError, ValueError):
            pass

    # Most recent daily Garmin metric of any kind.
    latest_metric_iso = (
        await session.execute(
            select(func.max(Metric.timestamp)).where(Metric.source == "garmin"),
        )
    ).scalar_one_or_none()
    hours_since_metric = _hours_since(latest_metric_iso, now, zone)

    # Most recent intra-day sample.
    latest_sample_iso = (
        await session.execute(
            select(func.max(MetricSample.timestamp))
            .where(MetricSample.source == "garmin"),
        )
    ).scalar_one_or_none()
    hours_since_sample = _hours_since(latest_sample_iso, now, zone)

    sleep_today_missing = (
        sleep_nights_behind is None or sleep_nights_behind > 0
    )
    samples_stale = (
        hours_since_sample is None or hours_since_sample > SAMPLE_STALE_HOURS
    )
    severe = (
        hours_since_metric is None
        or hours_since_metric > DAILY_SEVERE_STALE_HOURS
    )

    # Classify in worst-first order.
    if severe:
        status = "stale_severe"
        advisory = (
            "No Garmin data has reached the backend for more than 36 hours. "
            "Either the watch has not synced with the Garmin Connect phone "
            "app for that long, or Garmin auth on the backend is broken. "
            "Ask the user to open Garmin Connect on their phone and pull-to-"
            "refresh; if that doesn't help, ask them to check the Garmin "
            "credentials in the .env file."
        )
    elif sleep_today_missing:
        nights = sleep_nights_behind if sleep_nights_behind is not None else "?"
        status = "stale_today"
        advisory = (
            f"Last night's sleep is NOT in the database. Latest sleep row is "
            f"for wake date {latest_sleep_wake_date or 'n/a'} "
            f"({nights} night(s) behind today, {today.isoformat()}). The "
            f"watch likely has not synced with the Garmin Connect phone app "
            f"since waking. Do NOT answer about 'today's sleep / HRV / "
            f"readiness' from older rows as if they were last night's — tell "
            f"the user the data is missing and ask them to open Garmin "
            f"Connect on their phone to sync."
        )
    elif samples_stale:
        hrs = "unknown" if hours_since_sample is None else f"{hours_since_sample:.1f}h"
        status = "stale_intraday"
        advisory = (
            f"Daily aggregates look current, but the most recent intra-day "
            f"sample is {hrs} old (threshold {SAMPLE_STALE_HOURS}h). Today's "
            f"body battery, intra-day HR, and stress are stale — the watch "
            f"is no longer streaming to Garmin Connect. Tell the user to "
            f"open the Garmin Connect app to resume sync before relying on "
            f"these numbers for 'right now' answers."
        )
    else:
        status = "fresh"
        advisory = "Garmin data is current."

    return {
        "as_of": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "latest_sleep_wake_date": latest_sleep_wake_date,
        "sleep_nights_behind": sleep_nights_behind,
        "latest_metric_at": latest_metric_iso,
        "hours_since_latest_metric": (
            round(hours_since_metric, 2) if hours_since_metric is not None else None
        ),
        "latest_sample_at": latest_sample_iso,
        "hours_since_latest_sample": (
            round(hours_since_sample, 2) if hours_since_sample is not None else None
        ),
        "status": status,
        "is_stale": status != "fresh",
        "advisory": advisory,
    }


def _hours_since(iso: str | None, now: datetime, zone: ZoneInfo) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


__all__ = [
    "DAILY_SEVERE_STALE_HOURS",
    "SAMPLE_STALE_HOURS",
    "get_data_freshness",
]
