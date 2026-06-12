"""Tests for the P3-3 Garmin-staleness watchdog in alert_checker."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from lattice.functions import alert_checker
from lattice.functions.alert_checker import (
    _STALE_WATCHDOG_RULE_ID,
    run_alert_check,
)
from lattice.models import Metric, MetricSample
from lattice.models.alert import AlertEvent

TZ = "Europe/Warsaw"


@pytest.fixture
def _capture_dm(monkeypatch):  # type: ignore[no-untyped-def]
    sent: list[str] = []

    async def fake_send(content: str) -> bool:
        sent.append(content)
        return True

    monkeypatch.setattr(alert_checker, "send_dm", fake_send)
    return sent


async def _fresh(session) -> None:
    now = datetime.now(ZoneInfo(TZ))
    session.add(Metric(
        timestamp=now.replace(hour=0, minute=0).isoformat(),
        metric_name="sleep_score", value=80, unit="score", source="garmin",
    ))
    session.add(Metric(
        timestamp=(now - timedelta(hours=1)).isoformat(),
        metric_name="steps", value=1000, unit=None, source="garmin",
    ))
    session.add(MetricSample(
        timestamp=(now - timedelta(minutes=10)).isoformat(),
        metric_name="hr", value=60, source="garmin",
    ))
    await session.commit()


@pytest.mark.asyncio
async def test_watchdog_fires_when_no_data(db_session, _capture_dm) -> None:  # type: ignore[no-untyped-def]
    fired = await run_alert_check(db_session)
    assert fired == 1
    assert len(_capture_dm) == 1
    assert "stale" in _capture_dm[0].lower()

    events = list((await db_session.execute(
        select(AlertEvent).where(AlertEvent.rule_id == _STALE_WATCHDOG_RULE_ID),
    )).scalars().all())
    assert len(events) == 1


@pytest.mark.asyncio
async def test_watchdog_silent_when_fresh(db_session, _capture_dm) -> None:  # type: ignore[no-untyped-def]
    await _fresh(db_session)
    fired = await run_alert_check(db_session)
    assert fired == 0
    assert _capture_dm == []


@pytest.mark.asyncio
async def test_watchdog_cooldown_suppresses_repeat(db_session, _capture_dm) -> None:  # type: ignore[no-untyped-def]
    first = await run_alert_check(db_session)
    second = await run_alert_check(db_session)
    assert first == 1
    assert second == 0  # cooldown blocks the repeat DM
    assert len(_capture_dm) == 1
