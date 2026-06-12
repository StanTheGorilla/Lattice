"""Tests for functions/data_freshness.py (P2-2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.data_freshness import get_data_freshness
from lattice.models import Metric, MetricSample

TZ = "Europe/Warsaw"


async def _add_metric(session, name: str, when: datetime, *, source: str = "garmin") -> None:
    session.add(
        Metric(
            timestamp=when.isoformat(),
            metric_name=name,
            value=80.0,
            unit="score",
            source=source,
        ),
    )
    await session.commit()


async def _add_sample(session, when: datetime) -> None:
    session.add(
        MetricSample(
            timestamp=when.isoformat(),
            metric_name="hr",
            value=60.0,
            source="garmin",
        ),
    )
    await session.commit()


@pytest.mark.asyncio
async def test_no_data_is_severe(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await get_data_freshness(db_session)
    assert out["status"] == "stale_severe"
    assert out["is_stale"] is True


@pytest.mark.asyncio
async def test_fresh_when_recent_sleep_and_samples(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(ZoneInfo(TZ))
    # sleep_score row anchored to today's wake date
    await _add_metric(db_session, "sleep_score", now.replace(hour=0, minute=0))
    await _add_metric(db_session, "hrv_overnight_avg", now - timedelta(hours=2))
    await _add_sample(db_session, now - timedelta(minutes=10))

    out = await get_data_freshness(db_session)
    assert out["status"] == "fresh"
    assert out["is_stale"] is False
    assert out["sleep_nights_behind"] == 0


@pytest.mark.asyncio
async def test_stale_today_when_sleep_behind(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(ZoneInfo(TZ))
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=0)
    await _add_metric(db_session, "sleep_score", yesterday)
    # fresh daily metric + sample so we don't trip severe/intraday
    await _add_metric(db_session, "steps", now - timedelta(hours=1))
    await _add_sample(db_session, now - timedelta(minutes=10))

    out = await get_data_freshness(db_session)
    assert out["status"] == "stale_today"
    assert out["sleep_nights_behind"] == 1
