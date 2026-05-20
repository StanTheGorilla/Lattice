"""Change point detection for daily metric time series.

Uses a sliding-window mean-shift approach: for each day t, compare the
trailing 7-day mean to the preceding 21-day mean. A change point is
flagged when the z-score of the shift exceeds a threshold.

No scipy dependency — pure stdlib math.
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

_SHORT = 7    # days in 'recent' window
_LONG = 28   # days in 'baseline' window
_MIN_LONG = 14  # minimum baseline days required
_Z_THRESHOLD = 1.8  # SD threshold for flagging a shift


def _mean_sd(vals: list[float]) -> tuple[float, float]:
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    m = sum(vals) / n
    if n < 2:
        return m, 0.0
    sd = sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    return m, sd


async def detect_changepoints(
    session: AsyncSession,
    *,
    metric_name: str,
    days: int = 90,
    z_threshold: float = _Z_THRESHOLD,
) -> dict[str, Any]:
    """Detect significant mean-shift change points in a metric's recent history.

    Returns:
      metric           metric name
      changepoints     list of {date, before_mean, after_mean, delta, direction, z_score}
                       ordered by date, most recent first
      n_points         total data points analysed
      series_mean      overall mean across the window
      series_sd        overall SD
      interpretation   human-readable summary
      low_confidence   true when n_points < 21
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    start = today - timedelta(days=days - 1)

    stmt = select(Metric).where(
        Metric.metric_name == metric_name,
        Metric.timestamp >= start.isoformat(),
    ).order_by(Metric.timestamp.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    by_date: dict[str, float] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date().isoformat()
        except (ValueError, TypeError):
            continue
        by_date[d] = float(r.value)

    all_dates = sorted(by_date.keys())
    vals = [by_date[d] for d in all_dates]
    n = len(vals)

    if n < _MIN_LONG:
        return {
            "metric": metric_name,
            "changepoints": [],
            "n_points": n,
            "series_mean": round(sum(vals) / n, 2) if n else None,
            "series_sd": None,
            "interpretation": f"insufficient data ({n} points; need ≥{_MIN_LONG})",
            "low_confidence": True,
        }

    overall_mean, overall_sd = _mean_sd(vals)

    changepoints: list[dict[str, Any]] = []

    for i in range(_MIN_LONG, n):
        # Recent window: last _SHORT days ending at i (inclusive)
        short_start = max(0, i - _SHORT + 1)
        short_vals = vals[short_start : i + 1]

        # Baseline window: the _LONG days immediately before short window
        base_end = short_start
        base_start = max(0, base_end - _LONG)
        base_vals = vals[base_start:base_end]

        if len(base_vals) < _MIN_LONG // 2 or len(short_vals) < 3:
            continue

        base_mean, base_sd = _mean_sd(base_vals)
        short_mean, _ = _mean_sd(short_vals)

        # Pooled SD for z-score
        pooled_sd = base_sd if base_sd > 0 else overall_sd
        if pooled_sd == 0:
            continue

        z = (short_mean - base_mean) / pooled_sd
        if abs(z) >= z_threshold:
            date_of_change = all_dates[i]
            # Avoid duplicating adjacent detections (de-dup within 3 days)
            if changepoints and (
                datetime.fromisoformat(date_of_change).date()
                - datetime.fromisoformat(changepoints[-1]["date"]).date()
            ).days < 3:
                # Keep the higher |z|
                if abs(z) > abs(changepoints[-1]["z_score"]):
                    changepoints[-1] = {
                        "date": date_of_change,
                        "before_mean": round(base_mean, 2),
                        "after_mean": round(short_mean, 2),
                        "delta": round(short_mean - base_mean, 2),
                        "direction": "up" if z > 0 else "down",
                        "z_score": round(z, 2),
                    }
            else:
                changepoints.append({
                    "date": date_of_change,
                    "before_mean": round(base_mean, 2),
                    "after_mean": round(short_mean, 2),
                    "delta": round(short_mean - base_mean, 2),
                    "direction": "up" if z > 0 else "down",
                    "z_score": round(z, 2),
                })

    # Sort most recent first
    changepoints.sort(key=lambda x: x["date"], reverse=True)

    if not changepoints:
        interp = f"{metric_name} has been stable over the past {days} days (no significant mean shifts detected)"
    else:
        recent = changepoints[0]
        interp = (
            f"Most recent change: {metric_name} shifted {recent['direction']} on {recent['date']} "
            f"({recent['before_mean']} → {recent['after_mean']}, Δ={recent['delta']:+.1f}, z={recent['z_score']:.1f}). "
            f"{len(changepoints)} total change point{'s' if len(changepoints) > 1 else ''} detected."
        )

    return {
        "metric": metric_name,
        "changepoints": changepoints,
        "n_points": n,
        "series_mean": round(overall_mean, 2),
        "series_sd": round(overall_sd, 2),
        "interpretation": interp,
        "low_confidence": n < 21,
    }


__all__ = ["detect_changepoints"]
