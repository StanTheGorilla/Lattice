"""F3 — training recommendation rule table tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.training_rec import compute_training_rec
from tests.conftest import add_calendar_event, add_metric

TZ = "Europe/Warsaw"
ZONE = ZoneInfo(TZ)
TODAY = date(2026, 5, 14)


async def _seed_loads(session, acute: float, chronic: float) -> None:
    await add_metric(session, "training_load_acute", acute, TODAY)
    await add_metric(session, "training_load_chronic", chronic, TODAY)


@pytest.mark.asyncio
async def test_rest_when_readiness_below_40(db_session) -> None:
    await _seed_loads(db_session, 300, 400)
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=30)
    assert out.recommendation == "rest"


@pytest.mark.asyncio
async def test_easy_when_ac_ratio_above_1_5(db_session) -> None:
    await _seed_loads(db_session, 700, 400)  # ratio 1.75
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=70)
    assert out.recommendation == "easy"


@pytest.mark.asyncio
async def test_moderate_when_underloaded_and_ready(db_session) -> None:
    await _seed_loads(db_session, 280, 400)  # ratio 0.7
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=70)
    assert out.recommendation == "moderate"


@pytest.mark.asyncio
async def test_hard_when_high_readiness_and_rested(db_session) -> None:
    await _seed_loads(db_session, 400, 400)  # ratio 1.0
    # No high-intensity workout in last 30 days → days_since_hard >= 2
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=80)
    assert out.recommendation == "hard"


@pytest.mark.asyncio
async def test_default_moderate(db_session) -> None:
    await _seed_loads(db_session, 400, 400)  # ratio 1.0
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=70)
    assert out.recommendation == "moderate"


@pytest.mark.asyncio
async def test_meeting_cap_drops_hard_to_moderate(db_session) -> None:
    await _seed_loads(db_session, 400, 400)
    # 5h of meetings → should cap hard → moderate
    for h in range(9, 14):
        await add_calendar_event(
            db_session,
            event_id=f"m{h}",
            start=datetime.combine(TODAY, time(hour=h), tzinfo=ZONE),
            end=datetime.combine(TODAY, time(hour=h + 1), tzinfo=ZONE),
        )
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=80)
    assert out.recommendation == "moderate"
    assert any("capping" in r for r in out.rationale)


@pytest.mark.asyncio
async def test_no_chronic_load_easy_low_confidence(db_session) -> None:
    out = await compute_training_rec(db_session, target=TODAY, tz=TZ, readiness_score=70)
    assert out.recommendation == "easy"
    assert out.confidence == 0.3
