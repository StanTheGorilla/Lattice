"""Sleep debt calculator.

Computes cumulative sleep deficit vs the user's age-aware healthy floor.

Coherence (P1-2 / Rework R): sleep_debt and F4 must agree on what "below
target" means. Both now use `_healthy_sleep_bounds_min(age)` as the floor
(teens 8 h, adults 7 h, etc.), with `Profile.target_sleep_min` as an explicit
override. The old flat 450-min fallback is gone — without an override or a
birthday, sleep_debt falls back to the adult 7 h floor exactly like F4.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import metric_for_day_range
from lattice.functions.sleep_window import _age_on
from lattice.models import Profile


async def compute_sleep_debt(
    session: AsyncSession,
    *,
    days: int = 7,
    tz: str,
) -> dict[str, Any]:
    """Return sleep-debt stats for the last `days` nights.

    Fields returned:
      target_min          nightly target in minutes
      profile_target_used true when the Profile row's target_sleep_min was used
      window_days         the `days` parameter
      days_checked        nights where sleep data exists
      days_below_target   count of nights below target
      total_deficit_min   sum of nightly deficits (no surplus offsets)
      avg_deficit_min     total / days_checked (null when no data)
      per_day             [{date, sleep_min, deficit_min}]
      worst_night         entry with the largest deficit
      best_night          entry with the smallest deficit (most sleep)
    """
    zone = ZoneInfo(tz)
    today = datetime.now(zone).date()
    start = today - timedelta(days=days - 1)

    profile = await session.get(Profile, 1)
    if profile is not None and profile.target_sleep_min:
        target_min: int = profile.target_sleep_min
        profile_target_used = True
    else:
        # V-2: read the AI-writable sleep floor (defaults to F4's age-aware
        # seed when no AI row exists). Both tools now answer "below target"
        # the same way.
        age = _age_on(profile.birthday if profile is not None else None, today)
        from lattice.functions.health_targets import get_sleep_bounds_min
        floor_min, _ceil, _floor_src, _ceil_src = await get_sleep_bounds_min(
            session, age=age,
        )
        target_min = int(floor_min)
        profile_target_used = False

    rows = await metric_for_day_range(session, "sleep_duration_min", start, today, tz)
    by_date: dict[date, float] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date()
            by_date[d] = float(r.value)
        except (ValueError, TypeError):
            continue

    per_day: list[dict[str, Any]] = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d in by_date:
            sleep = by_date[d]
            deficit = max(0.0, target_min - sleep)
            per_day.append({
                "date": d.isoformat(),
                "sleep_min": round(sleep, 1),
                "deficit_min": round(deficit, 1),
            })

    days_checked = len(per_day)
    total = sum(r["deficit_min"] for r in per_day)
    days_below = sum(1 for r in per_day if r["deficit_min"] > 0)
    avg = round(total / days_checked, 1) if days_checked > 0 else None
    worst = max(per_day, key=lambda r: r["deficit_min"], default=None)
    best = min(per_day, key=lambda r: r["sleep_min"], default=None)

    return {
        "target_min": target_min,
        "profile_target_used": profile_target_used,
        "window_days": days,
        "days_checked": days_checked,
        "days_below_target": days_below,
        "total_deficit_min": round(total, 1),
        "avg_deficit_min": avg,
        "per_day": per_day,
        "worst_night": worst,
        "best_night": best,
    }


__all__ = ["compute_sleep_debt"]
