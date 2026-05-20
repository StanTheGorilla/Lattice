"""Trend direction analysis for metrics.

Uses ordinary least squares regression on daily values to answer:
"Is this metric improving, declining, or stable over the window?"

The `direction` field is pre-interpreted using the metric's sign convention
(higher-is-better vs lower-is-better) so callers never need to know it.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric, MetricSample

# Metrics where LOWER values are better. All others assumed higher-is-better.
_LOWER_IS_BETTER: frozenset[str] = frozenset({
    "resting_hr",
    "stress_avg", "stress_max",
    "sleep_awake_min", "restless_moments_count",
    "hr", "stress",
})

TREND_MIN_N = 5              # below this n, always report "stable"
TREND_MIN_R2 = 0.15          # below this R², direction is unreliable → "stable"

_SAMPLE_NAMES: frozenset[str] = frozenset({"hr", "stress", "body_battery"})

_UNITS: dict[str, str] = {
    "hrv_overnight_avg": "ms",
    "resting_hr": "bpm",
    "hr": "bpm",
    "sleep_duration_min": "min",
    "sleep_deep_min": "min",
    "sleep_rem_min": "min",
    "sleep_score": "pts",
    "body_battery_start": "pts",
    "stress_avg": "pts",
    "vo2_max": "ml/kg/min",
    "steps": "steps",
}


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _from_bound(s: str | None, default_days_back: int = 30) -> str:
    tz = _tz()
    if s is None:
        d = datetime.now(tz).date() - timedelta(days=default_days_back - 1)
        return datetime.combine(d, time.min, tzinfo=tz).isoformat()
    if len(s) == 10:
        try:
            return datetime.combine(date.fromisoformat(s), time.min, tzinfo=tz).isoformat()
        except ValueError:
            pass
    return s


def _to_bound(s: str | None) -> str:
    tz = _tz()
    if s is None:
        d = datetime.now(tz).date()
        return datetime.combine(d, time.max, tzinfo=tz).isoformat()
    if len(s) == 10:
        try:
            return datetime.combine(date.fromisoformat(s), time.max, tzinfo=tz).isoformat()
        except ValueError:
            pass
    return s


def _ols(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """OLS: returns (slope, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2 = sum(x * x for x in xs)
    denom = n * sx2 - sx * sx
    if denom == 0:
        return 0.0, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot == 0:
        return slope, 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return slope, r2


async def trend_direction(
    session: AsyncSession,
    metric_name: str,
    from_: str | None = None,
    to_: str | None = None,
) -> dict[str, Any]:
    """Compute trend direction for a metric over a date window.

    Returns:
      direction       "improving" | "declining" | "stable"
      slope_per_day   raw OLS slope (positive = rising, negative = falling)
      r_squared       goodness-of-fit [0, 1]
      n               data points used
      low_confidence  true when n < 5 or R² < 0.15
      interpretation  plain-text one-liner
      lower_is_better whether smaller values are healthier for this metric
    """
    from_s = _from_bound(from_, default_days_back=30)
    to_s = _to_bound(to_)
    tz = _tz()

    is_sample = metric_name in _SAMPLE_NAMES
    by_date: dict[date, list[float]] = {}

    if is_sample:
        stmt = (
            select(MetricSample.timestamp, MetricSample.value)
            .where(
                MetricSample.metric_name == metric_name,
                MetricSample.timestamp >= from_s,
                MetricSample.timestamp <= to_s,
            )
            .order_by(MetricSample.timestamp.asc())
        )
        for ts_str, val in (await session.execute(stmt)).all():
            try:
                d = datetime.fromisoformat(ts_str).astimezone(tz).date()
                by_date.setdefault(d, []).append(float(val))
            except (ValueError, TypeError):
                continue
        # Aggregate to daily median
        daily: list[tuple[int, float]] = []
        for i, d in enumerate(sorted(by_date)):
            daily.append((i, statistics.median(by_date[d])))
    else:
        stmt2 = (
            select(Metric.timestamp, Metric.value)
            .where(
                Metric.metric_name == metric_name,
                Metric.timestamp >= from_s,
                Metric.timestamp <= to_s,
            )
            .order_by(Metric.timestamp.asc())
        )
        day_vals: dict[date, float] = {}
        for ts_str, val in (await session.execute(stmt2)).all():
            try:
                d = datetime.fromisoformat(ts_str).astimezone(tz).date()
                day_vals[d] = float(val)
            except (ValueError, TypeError):
                continue
        daily = [(i, v) for i, (_, v) in enumerate(sorted(day_vals.items()))]

    n = len(daily)
    if n == 0:
        return _empty(metric_name, from_s, to_s, "no data")
    if n < 2:
        return _empty(metric_name, from_s, to_s, f"only {n} data point")

    xs = [float(x) for x, _ in daily]
    ys = [float(y) for _, y in daily]
    slope, r2 = _ols(xs, ys)
    low_conf = n < TREND_MIN_N or r2 < TREND_MIN_R2

    lower_better = metric_name in _LOWER_IS_BETTER
    if low_conf:
        direction = "stable"
    elif lower_better:
        direction = "improving" if slope < -0.001 else ("declining" if slope > 0.001 else "stable")
    else:
        direction = "improving" if slope > 0.001 else ("declining" if slope < -0.001 else "stable")

    unit = _UNITS.get(metric_name, "pts")
    if direction == "stable":
        interp = f"{metric_name}: stable over {n} days (slope {slope:+.3f} {unit}/day, R²={r2:.2f})"
    else:
        interp = (
            f"{metric_name}: {direction} over {n} days — "
            f"{slope:+.3f} {unit}/day, R²={r2:.2f}"
        )
    if low_conf:
        interp += " (low confidence)"

    return {
        "metric": metric_name,
        "from": from_s,
        "to": to_s,
        "n": n,
        "direction": direction,
        "slope_per_day": round(slope, 4),
        "r_squared": round(r2, 3),
        "low_confidence": low_conf,
        "lower_is_better": lower_better,
        "interpretation": interp,
    }


def _empty(metric: str, from_s: str, to_s: str, reason: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "from": from_s,
        "to": to_s,
        "n": 0,
        "direction": "stable",
        "slope_per_day": 0.0,
        "r_squared": 0.0,
        "low_confidence": True,
        "lower_is_better": metric in _LOWER_IS_BETTER,
        "interpretation": f"{metric}: {reason}",
    }


__all__ = ["trend_direction"]
