"""Shared baseline + metric-fetch helpers used by F1–F5.

All functions are pure (take a session + params, no globals). They run a
simple ORDER BY timestamp DESC LIMIT n on the metrics table — the dataset
is single-user and rarely larger than a few thousand rows, so this is fast
enough without indexed aggregations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import sqrt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.models import Metric


@dataclass(slots=True)
class Baseline:
    name: str
    mean: float | None
    sd: float | None
    n: int
    window_days: int


async def compute_baseline(
    session: AsyncSession,
    name: str,
    *,
    days: int = 14,
    before: date | None = None,
    tz: str = "UTC",
) -> Baseline:
    """Mean/SD over the most recent `days` rows for `name`.

    If `before` is set, only rows with timestamp strictly earlier than
    midnight of `before` in `tz` are considered — useful when the baseline
    must exclude the target day's own value (e.g. F1 readiness z-scores).
    """
    stmt = select(Metric.value).where(Metric.metric_name == name)
    if before is not None:
        cutoff_iso = datetime.combine(before, time.min, tzinfo=ZoneInfo(tz)).isoformat()
        stmt = stmt.where(Metric.timestamp < cutoff_iso)
    stmt = stmt.order_by(Metric.timestamp.desc()).limit(days)
    values = [float(v) for v in (await session.execute(stmt)).scalars().all()]
    n = len(values)
    if n == 0:
        return Baseline(name=name, mean=None, sd=None, n=0, window_days=days)
    mean = sum(values) / n
    if n < 2:
        return Baseline(name=name, mean=mean, sd=None, n=n, window_days=days)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return Baseline(name=name, mean=mean, sd=sqrt(variance), n=n, window_days=days)


async def latest_metric(session: AsyncSession, name: str) -> Metric | None:
    stmt = (
        select(Metric)
        .where(Metric.metric_name == name)
        .order_by(Metric.timestamp.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def metric_on_date(
    session: AsyncSession, name: str, day: date, tz: str,
) -> Metric | None:
    """Return the metric anchored at midnight of `day` in `tz`, if present."""
    iso = datetime.combine(day, time.min, tzinfo=ZoneInfo(tz)).isoformat()
    stmt = (
        select(Metric)
        .where(Metric.metric_name == name, Metric.timestamp == iso)
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def metric_for_day_range(
    session: AsyncSession,
    name: str,
    start_day: date,
    end_day: date,
    tz: str,
) -> list[Metric]:
    """Inclusive on both ends. Returns rows ordered by timestamp ascending."""
    zone = ZoneInfo(tz)
    start_iso = datetime.combine(start_day, time.min, tzinfo=zone).isoformat()
    end_iso = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=zone).isoformat()
    stmt = (
        select(Metric)
        .where(
            Metric.metric_name == name,
            Metric.timestamp >= start_iso,
            Metric.timestamp < end_iso,
        )
        .order_by(Metric.timestamp.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


def clamp(v: float, low: float, high: float) -> float:
    return max(low, min(high, v))


def parse_iso(value: str) -> datetime:
    """Return a tz-aware datetime from an ISO 8601 string. Falls back to UTC."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt


__all__ = [
    "Baseline",
    "clamp",
    "compute_baseline",
    "latest_metric",
    "metric_for_day_range",
    "metric_on_date",
    "parse_iso",
]
