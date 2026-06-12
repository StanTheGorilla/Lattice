"""Tests for the proactive alert checker (the hourly job / manual check)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from sqlalchemy import select

from lattice.functions import alert_checker
from lattice.models.alert import AlertEvent, AlertRule

from .conftest import add_metric


@pytest.fixture(autouse=True)
def _silence_staleness_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests target user-defined rule logic only.

    `run_alert_check` also runs the P3-3 Garmin-staleness watchdog, which fires
    on the deliberately-old fixture metrics here. Stub freshness to a fresh
    status so the watchdog stays silent; it has dedicated coverage in
    `test_staleness_watchdog.py`.
    """

    async def fresh(_session: Any) -> dict[str, Any]:
        return {"status": "fresh", "hours_since_latest_metric": 1.0, "advisory": ""}

    monkeypatch.setattr(alert_checker, "get_data_freshness", fresh)


async def _add_rule(session: Any, **kw: Any) -> AlertRule:
    rule = AlertRule(
        metric_name=kw.get("metric_name", "hrv_overnight_avg"),
        operator=kw.get("operator", "lt"),
        threshold=kw.get("threshold", 40.0),
        label=kw.get("label", "HRV low"),
        cooldown_hours=kw.get("cooldown_hours", 4),
        active=kw.get("active", True),
        created_at="2026-06-01T00:00:00+02:00",
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@pytest.mark.asyncio
async def test_rule_fires_when_threshold_crossed(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[str] = []

    async def fake_send_dm(content: str) -> bool:
        sent.append(content)
        return True

    monkeypatch.setattr(alert_checker, "send_dm", fake_send_dm)

    await add_metric(db_session, "hrv_overnight_avg", 30.0, date(2026, 6, 3))
    await _add_rule(db_session, metric_name="hrv_overnight_avg", operator="lt", threshold=40.0)

    fired = await alert_checker.run_alert_check(db_session)
    assert fired == 1
    assert len(sent) == 1
    events = (await db_session.execute(select(AlertEvent))).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_rule_does_not_fire_when_not_crossed(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_send_dm(content: str) -> bool:
        return True

    monkeypatch.setattr(alert_checker, "send_dm", fake_send_dm)

    await add_metric(db_session, "hrv_overnight_avg", 55.0, date(2026, 6, 3))
    await _add_rule(db_session, metric_name="hrv_overnight_avg", operator="lt", threshold=40.0)

    fired = await alert_checker.run_alert_check(db_session)
    assert fired == 0


@pytest.mark.asyncio
async def test_cooldown_suppresses_second_fire(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_send_dm(content: str) -> bool:
        return True

    monkeypatch.setattr(alert_checker, "send_dm", fake_send_dm)

    await add_metric(db_session, "resting_hr", 80.0, date(2026, 6, 3))
    await _add_rule(
        db_session, metric_name="resting_hr", operator="gt", threshold=70.0, cooldown_hours=4
    )

    first = await alert_checker.run_alert_check(db_session)
    second = await alert_checker.run_alert_check(db_session)
    assert first == 1
    assert second == 0  # cooldown window not elapsed


@pytest.mark.asyncio
async def test_inactive_rule_skipped(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_send_dm(content: str) -> bool:
        return True

    monkeypatch.setattr(alert_checker, "send_dm", fake_send_dm)

    await add_metric(db_session, "hrv_overnight_avg", 10.0, date(2026, 6, 3))
    await _add_rule(db_session, threshold=40.0, active=False)

    fired = await alert_checker.run_alert_check(db_session)
    assert fired == 0
