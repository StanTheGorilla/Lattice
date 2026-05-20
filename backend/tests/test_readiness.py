"""F1 — readiness scoring tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from lattice.functions.readiness import compute_readiness
from tests.conftest import add_metric

TZ = "Europe/Warsaw"
TODAY = date(2026, 5, 14)


async def _seed_baseline_history(session, *, days: int = 14) -> None:
    """Seed `days` days of HRV and RHR ending the day before TODAY.

    Alternating ±1 keeps the mean exact (50/55) and sd > 0 (z-score needs it).
    """
    for i in range(1, days + 1):
        day = TODAY - timedelta(days=i)
        bump = 1 if i % 2 == 0 else -1
        await add_metric(session, "hrv_overnight_avg", 50.0 + bump, day)
        await add_metric(session, "resting_hr", 55.0 + bump, day)


@pytest.mark.asyncio
async def test_full_data_score_in_range(db_session) -> None:
    await _seed_baseline_history(db_session)
    # Today's values exactly on baseline mean → z=0 → 0.5 each
    await add_metric(db_session, "hrv_overnight_avg", 50.0, TODAY)
    await add_metric(db_session, "sleep_score", 80.0, TODAY)
    await add_metric(db_session, "resting_hr", 55.0, TODAY)
    await add_metric(db_session, "body_battery_start", 90.0, TODAY)
    await add_metric(db_session, "stress_avg", 30.0, TODAY - timedelta(days=1))

    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    # hrv 0.5, sleep 0.8, rhr 0.5, bb 0.9, stress 0.7
    # 0.40*0.5 + 0.30*0.8 + 0.15*0.5 + 0.10*0.9 + 0.05*0.7 = 0.64 → 64
    assert result.score == 64
    assert result.category == "average"
    assert result.provisional is False
    assert result.explanation.missing == []


@pytest.mark.asyncio
async def test_provisional_under_7_days(db_session) -> None:
    await _seed_baseline_history(db_session, days=3)
    await add_metric(db_session, "hrv_overnight_avg", 50.0, TODAY)
    await add_metric(db_session, "sleep_score", 80.0, TODAY)
    await add_metric(db_session, "resting_hr", 55.0, TODAY)
    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    assert result.provisional is True
    assert any("provisional" in n for n in result.explanation.notes)


@pytest.mark.asyncio
async def test_missing_hrv_renormalizes(db_session) -> None:
    await _seed_baseline_history(db_session)
    # Skip HRV today entirely
    await add_metric(db_session, "sleep_score", 80.0, TODAY)
    await add_metric(db_session, "resting_hr", 55.0, TODAY)
    await add_metric(db_session, "body_battery_start", 80.0, TODAY)

    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    assert "hrv" in result.explanation.missing
    # Weights sum to 1 even with HRV gone.
    total_w = sum(result.explanation.weights_used.values())
    assert abs(total_w - 1.0) < 1e-9


@pytest.mark.asyncio
async def test_no_data_returns_zero(db_session) -> None:
    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    assert result.score == 0
    assert result.category == "depleted"
    assert result.provisional is True


@pytest.mark.asyncio
async def test_peak_category(db_session) -> None:
    await _seed_baseline_history(db_session)
    # Push all components to max
    await add_metric(db_session, "hrv_overnight_avg", 70.0, TODAY)  # +z capped at +2
    await add_metric(db_session, "sleep_score", 100.0, TODAY)
    await add_metric(db_session, "resting_hr", 45.0, TODAY)  # -z (lower=better) capped at +2
    await add_metric(db_session, "body_battery_start", 100.0, TODAY)
    await add_metric(db_session, "stress_avg", 0.0, TODAY - timedelta(days=1))
    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    assert result.score == 100
    assert result.category == "peak"


@pytest.mark.asyncio
async def test_depleted_category(db_session) -> None:
    await _seed_baseline_history(db_session)
    # Drive all components low
    await add_metric(db_session, "hrv_overnight_avg", 30.0, TODAY)
    await add_metric(db_session, "sleep_score", 20.0, TODAY)
    await add_metric(db_session, "resting_hr", 65.0, TODAY)
    await add_metric(db_session, "body_battery_start", 10.0, TODAY)
    await add_metric(db_session, "stress_avg", 90.0, TODAY - timedelta(days=1))
    result = await compute_readiness(db_session, target=TODAY, tz=TZ)
    assert result.score < 35
    assert result.category == "depleted"
