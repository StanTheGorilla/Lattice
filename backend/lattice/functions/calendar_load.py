"""Calendar-load aggregator — meeting hours per day for correlations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.stats import _normalize_from, _normalize_to
from lattice.models import CalendarCache


async def busy_hours_per_day(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """For each calendar day in [from, to], total busy hours from timed events.

    All-day events are excluded (they're not "busy" in the cognitive-load sense).
    """
    f = _normalize_from(from_iso, default_days_back=14)
    t = _normalize_to(to_iso)
    tz = ZoneInfo(settings.timezone)

    stmt = (
        select(CalendarCache)
        .where(CalendarCache.is_all_day == 0)
        .where(CalendarCache.end >= f)
        .where(CalendarCache.start <= t)
    )
    rows = (await session.execute(stmt)).scalars().all()

    by_day: dict[str, float] = {}
    for ev in rows:
        try:
            start_dt = datetime.fromisoformat(ev.start).astimezone(tz)
            end_dt = datetime.fromisoformat(ev.end).astimezone(tz)
        except ValueError:
            continue
        if end_dt <= start_dt:
            continue
        # Split across day boundaries if the event spans midnight.
        cur = start_dt
        while cur < end_dt:
            day = cur.date()
            next_midnight = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
            slice_end = min(end_dt, next_midnight)
            hours = (slice_end - cur).total_seconds() / 3600.0
            key = day.isoformat()
            by_day[key] = round(by_day.get(key, 0.0) + hours, 3)
            cur = slice_end

    series = [{"date": d, "busy_hours": h} for d, h in sorted(by_day.items())]
    return {"from": f, "to": t, "n": len(series), "series": series}
