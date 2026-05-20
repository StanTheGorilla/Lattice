"""Unit tests for body_battery_drop_rate + body_battery_hourly_deltas."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.stats import (
    body_battery_drop_rate,
    body_battery_hourly_deltas,
)
from lattice.models import MetricSample

TZ = "Europe/Warsaw"


def _add(db: AsyncSession, *, dt: datetime, v: float) -> None:
    db.add(MetricSample(
        timestamp=dt.isoformat(),
        metric_name="body_battery",
        value=v,
        source="garmin",
    ))


@pytest.mark.asyncio
async def test_drop_rate_simple_daily_drain(db_session: AsyncSession) -> None:
    # 3 consecutive days, each: BB goes 80 → 50 between 09:00 and 14:00 (5h).
    # Drain = 30 points over 5h → rate = -6 pts/hr.
    for d in range(10, 13):
        start = datetime(2026, 5, d, 9, 0, tzinfo=ZoneInfo(TZ))
        _add(db_session, dt=start,                          v=80.0)
        _add(db_session, dt=start + timedelta(hours=5),     v=50.0)
    await db_session.commit()

    out = await body_battery_drop_rate(
        db_session, from_iso="2026-05-10", to_iso="2026-05-12",
        hour_start=9, hour_end=15,
    )
    assert out["n_days"] == 3
    assert out["median_rate_points_per_hour"] == -6.0
    assert out["median_drop_points"] == 30.0


@pytest.mark.asyncio
async def test_drop_rate_no_data(db_session: AsyncSession) -> None:
    out = await body_battery_drop_rate(
        db_session, from_iso="2026-05-10", to_iso="2026-05-12",
    )
    assert out["n_days"] == 0
    assert out["low_confidence"] is True
    assert out["median_rate_points_per_hour"] is None


@pytest.mark.asyncio
async def test_drop_rate_rejects_inverted_hours(db_session: AsyncSession) -> None:
    out = await body_battery_drop_rate(
        db_session, hour_start=12, hour_end=8,
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_hourly_deltas_detects_recurring_pattern(db_session: AsyncSession) -> None:
    # 5 days. At 14:00 each day BB goes 60 → 48 within the hour (-12).
    # At 10:00 each day BB goes 90 → 88 within the hour (-2).
    for d in range(10, 15):
        afternoon = datetime(2026, 5, d, 14, 0, tzinfo=ZoneInfo(TZ))
        _add(db_session, dt=afternoon,                          v=60.0)
        _add(db_session, dt=afternoon + timedelta(minutes=58),  v=48.0)
        morning = datetime(2026, 5, d, 10, 0, tzinfo=ZoneInfo(TZ))
        _add(db_session, dt=morning,                            v=90.0)
        _add(db_session, dt=morning + timedelta(minutes=58),    v=88.0)
    await db_session.commit()

    out = await body_battery_hourly_deltas(
        db_session, from_iso="2026-05-10", to_iso="2026-05-14",
    )
    assert out["hours"][14]["median_delta"] == -12.0
    assert out["hours"][14]["n_days"] == 5
    assert out["hours"][10]["median_delta"] == -2.0
    # Untouched hours: no data.
    assert out["hours"][3]["median_delta"] is None
