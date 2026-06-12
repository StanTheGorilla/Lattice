"""Unit tests for the alert-rule LLM tool handlers (Phase C)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from lattice.llm import router as llm_router
from lattice.models.alert import AlertRule


@pytest.mark.asyncio
async def test_create_alert_persists_rule(db_session: Any) -> None:
    out = await llm_router._h_create_alert(
        db_session,
        {
            "metric_name": "hrv_overnight_avg",
            "operator": "lt",
            "threshold": 40,
            "label": "HRV low",
        },
    )
    assert "error" not in out
    assert out["metric_name"] == "hrv_overnight_avg"
    assert out["operator"] == "lt"
    assert out["threshold"] == 40
    assert out["cooldown_hours"] == 4  # default
    assert out["active"] is True

    rows = (await db_session.execute(select(AlertRule))).scalars().all()
    assert len(rows) == 1
    assert rows[0].label == "HRV low"


@pytest.mark.asyncio
async def test_create_alert_rejects_bad_operator(db_session: Any) -> None:
    out = await llm_router._h_create_alert(
        db_session,
        {"metric_name": "hrv", "operator": "between", "threshold": 1, "label": "x"},
    )
    assert "error" in out
    rows = (await db_session.execute(select(AlertRule))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_create_alert_requires_threshold(db_session: Any) -> None:
    out = await llm_router._h_create_alert(
        db_session,
        {"metric_name": "hrv", "operator": "lt", "label": "x"},
    )
    assert "error" in out


@pytest.mark.asyncio
async def test_list_and_delete_alert(db_session: Any) -> None:
    created = await llm_router._h_create_alert(
        db_session,
        {
            "metric_name": "resting_hr",
            "operator": "gt",
            "threshold": 70,
            "label": "RHR high",
            "cooldown_hours": 6,
        },
    )
    rule_id = created["id"]

    listed = await llm_router._h_list_alerts(db_session, {})
    assert listed["count"] == 1
    assert listed["items"][0]["cooldown_hours"] == 6

    deleted = await llm_router._h_delete_alert(db_session, {"id": rule_id})
    assert deleted == {"deleted": rule_id}

    rows = (await db_session.execute(select(AlertRule))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_delete_missing_alert_errors(db_session: Any) -> None:
    out = await llm_router._h_delete_alert(db_session, {"id": 999})
    assert "error" in out
