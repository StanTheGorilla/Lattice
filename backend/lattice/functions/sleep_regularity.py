"""Sleep Regularity Index (SRI) and social jetlag.

SRI measures how consistent sleep timing is across days. Social jetlag
quantifies the mismatch between weekday and weekend sleep schedules.

Research basis:
- SRI (Phillips et al. 2017): predicts mental health and metabolic outcomes
  independently of sleep duration.
- Social jetlag (Wittmann et al. 2006): even 1h correlates with obesity,
  depression, and metabolic syndrome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sqrt
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric


def _mid_sleep_minutes(start_min: float, duration_min: float) -> float:
    """Mid-sleep point in minutes relative to noon (12:00 = 0).

    Using noon as reference avoids midnight wrap-around issues: a 23:00
    bedtime with 8h sleep gives mid = 3:00 AM = -540 min from noon,
    while a 22:00 bedtime same duration gives -600.
    Differences between consecutive nights are sign-agnostic.
    """
    mid_from_midnight = start_min + duration_min / 2.0
    # Normalise to [-720, 720] relative to noon (720 min from midnight)
    mid_from_noon = mid_from_midnight - 720.0
    # Wrap large values (e.g. 1500 min = 1:00 next day = -540 from noon+1day)
    if mid_from_noon > 720:
        mid_from_noon -= 1440
    elif mid_from_noon < -720:
        mid_from_noon += 1440
    return mid_from_noon


async def compute_sleep_regularity(
    session: AsyncSession,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """Compute Sleep Regularity Index and social jetlag.

    Returns:
      sri               0-100 (100 = perfectly regular)
      social_jetlag_h   absolute weekday-vs-weekend mid-sleep diff in hours
      mid_sleep_std_min SD of mid-sleep times in minutes
      n_nights          number of nights with usable data
      weekday_avg_midsleep_h  average mid-sleep on weekday nights (decimal hours from midnight)
      weekend_avg_midsleep_h  average mid-sleep on weekend nights
      interpretation    human-readable assessment
      low_confidence    true when n_nights < 7
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    start = today - timedelta(days=days - 1)

    # Fetch sleep_start_time and sleep_duration_min together
    stmt = select(Metric).where(
        Metric.metric_name.in_(["sleep_start_time", "sleep_duration_min"]),
        Metric.timestamp >= start.isoformat(),
    ).order_by(Metric.timestamp.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    # Group by date
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date().isoformat()
        except (ValueError, TypeError):
            continue
        by_date.setdefault(d, {})[r.metric_name] = float(r.value)

    # Collect nights with both values
    mid_sleeps: list[tuple[str, float]] = []  # (date_iso, mid_sleep_from_noon_minutes)
    for d_iso in sorted(by_date.keys()):
        d = by_date[d_iso]
        if "sleep_start_time" in d and "sleep_duration_min" in d:
            mid = _mid_sleep_minutes(d["sleep_start_time"], d["sleep_duration_min"])
            mid_sleeps.append((d_iso, mid))

    n = len(mid_sleeps)
    if n == 0:
        return {
            "sri": None, "social_jetlag_h": None,
            "mid_sleep_std_min": None, "n_nights": 0,
            "weekday_avg_midsleep_h": None, "weekend_avg_midsleep_h": None,
            "interpretation": "no sleep data",
            "low_confidence": True,
        }

    # SRI proxy: SD of mid-sleep times
    mids = [m for _, m in mid_sleeps]
    mean_mid = sum(mids) / n
    if n >= 2:
        var = sum((m - mean_mid) ** 2 for m in mids) / (n - 1)
        sd = sqrt(var)
    else:
        sd = 0.0

    # SRI: 100 = perfectly regular; each 15-min of SD costs ~10 points
    # At SD=0 → 100; at SD=60 → ~60; at SD=120 → ~20; at SD≥150 → 0
    sri = max(0.0, min(100.0, 100.0 - sd * (100.0 / 150.0)))

    # Social jetlag: weekday vs weekend mid-sleep
    # weekday = wake date is Mon-Fri (isoweekday 1-5)
    weekday_mids: list[float] = []
    weekend_mids: list[float] = []
    for d_iso, mid in mid_sleeps:
        wd = datetime.fromisoformat(d_iso).isoweekday()
        if wd <= 5:
            weekday_mids.append(mid)
        else:
            weekend_mids.append(mid)

    social_jetlag_h: float | None = None
    wd_avg: float | None = None
    we_avg: float | None = None
    if weekday_mids:
        wd_avg = (sum(weekday_mids) / len(weekday_mids) + 720) / 60.0  # hours from midnight
    if weekend_mids:
        we_avg = (sum(weekend_mids) / len(weekend_mids) + 720) / 60.0
    if wd_avg is not None and we_avg is not None:
        social_jetlag_h = round(abs(we_avg - wd_avg), 2)

    # Interpretation
    if sri >= 85:
        interp = "highly regular — excellent circadian stability"
    elif sri >= 70:
        interp = "moderate regularity — some timing drift"
    elif sri >= 50:
        interp = "irregular — meaningful circadian disruption"
    else:
        interp = "highly irregular — significant social jetlag risk"

    if social_jetlag_h is not None and social_jetlag_h >= 2.0:
        interp += f"; social jetlag {social_jetlag_h:.1f}h is clinically significant (>2h)"
    elif social_jetlag_h is not None and social_jetlag_h >= 1.0:
        interp += f"; social jetlag {social_jetlag_h:.1f}h (>1h linked to metabolic effects)"

    return {
        "sri": round(sri, 1),
        "social_jetlag_h": social_jetlag_h,
        "mid_sleep_std_min": round(sd, 1),
        "n_nights": n,
        "weekday_avg_midsleep_h": round(wd_avg, 2) if wd_avg is not None else None,
        "weekend_avg_midsleep_h": round(we_avg, 2) if we_avg is not None else None,
        "interpretation": interp,
        "low_confidence": n < 7,
    }


__all__ = ["compute_sleep_regularity"]
