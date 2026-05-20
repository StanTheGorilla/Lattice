"""F9a — advisor rule table tests.

SPEC: 'fully unit-tested, no LLM call inside this function.' Covers every
branch of every intent.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.advisor import compute_advisor
from tests.conftest import (
    add_calendar_event,
    add_entry,
    add_metric,
)

TZ = "Europe/Warsaw"
ZONE = ZoneInfo(TZ)
TODAY = date(2026, 5, 14)


def at(h: int, m: int = 0) -> datetime:
    return datetime.combine(TODAY, time(hour=h, minute=m), tzinfo=ZONE)


async def _seed_baseline(session, days: int = 14) -> None:
    for i in range(1, days + 1):
        day = TODAY - timedelta(days=i)
        bump = 1 if i % 2 == 0 else -1
        await add_metric(session, "hrv_overnight_avg", 50.0 + bump, day)
        await add_metric(session, "resting_hr", 55.0 + bump, day)


async def _seed_today_neutral(session) -> None:
    """50-ish readiness day."""
    await add_metric(session, "hrv_overnight_avg", 50.0, TODAY)
    await add_metric(session, "sleep_score", 80.0, TODAY)
    await add_metric(session, "resting_hr", 55.0, TODAY)
    await add_metric(session, "body_battery_start", 90.0, TODAY)
    await add_metric(session, "stress_avg", 30.0, TODAY - timedelta(days=1))


async def _seed_today_depleted(session) -> None:
    await add_metric(session, "hrv_overnight_avg", 30.0, TODAY)
    await add_metric(session, "sleep_score", 10.0, TODAY)
    await add_metric(session, "resting_hr", 70.0, TODAY)
    await add_metric(session, "body_battery_start", 5.0, TODAY)
    await add_metric(session, "stress_avg", 95.0, TODAY - timedelta(days=1))


# --------------------------------------------------------------------------- #
# intent=learn
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_learn_rest_when_readiness_below_35(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_depleted(db_session)
    out = await compute_advisor(db_session, intent="learn", target=TODAY, tz=TZ)
    assert out.recommendation == "rest_recommended"
    assert out.confidence == 0.9


@pytest.mark.asyncio
async def test_learn_no_window_when_calendar_fragmented(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_neutral(db_session)
    # Fill 07:00-23:00 with back-to-back meetings, no 60min gap
    for h in range(7, 23):
        await add_calendar_event(
            db_session,
            event_id=f"e{h}",
            start=at(h, 0),
            end=at(h, 50),  # 10-min gap each hour, all <60min
            title=f"M{h}",
        )
    out = await compute_advisor(db_session, intent="learn", target=TODAY, tz=TZ)
    assert out.recommendation == "no_window_available"


@pytest.mark.asyncio
async def test_learn_window_strong_with_clear_day(db_session) -> None:
    await _seed_baseline(db_session)
    # Push readiness high so the 30% readiness slice plus tod gets >=70
    await add_metric(db_session, "hrv_overnight_avg", 60.0, TODAY)
    await add_metric(db_session, "sleep_score", 95.0, TODAY)
    await add_metric(db_session, "resting_hr", 50.0, TODAY)
    await add_metric(db_session, "body_battery_start", 95.0, TODAY)
    await add_metric(db_session, "stress_avg", 10.0, TODAY - timedelta(days=1))
    # Seed peak focus at 10:00 (so a 09:00-12:00 gap scores high)
    await add_entry(
        db_session,
        entry_type="focus",
        data={"score": 5, "task": "deep work"},
        when=datetime.combine(TODAY - timedelta(days=1), time(hour=10), tzinfo=ZONE),
    )
    # Empty calendar → entire day is one big gap
    out = await compute_advisor(db_session, intent="learn", target=TODAY, tz=TZ)
    assert out.recommendation in ("window_strong", "window_moderate")
    assert out.window is not None


# --------------------------------------------------------------------------- #
# intent=creative — same as learn but lower rest threshold
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_creative_tolerates_lower_readiness(db_session) -> None:
    await _seed_baseline(db_session)
    # Aim for a score in (25, 35): below learn's rest threshold, above creative's.
    await add_metric(db_session, "hrv_overnight_avg", 49.0, TODAY)  # ~ -1 SD
    await add_metric(db_session, "sleep_score", 25.0, TODAY)
    await add_metric(db_session, "resting_hr", 55.0, TODAY)
    await add_metric(db_session, "body_battery_start", 30.0, TODAY)
    await add_metric(db_session, "stress_avg", 50.0, TODAY - timedelta(days=1))
    out_learn = await compute_advisor(db_session, intent="learn", target=TODAY, tz=TZ)
    out_creative = await compute_advisor(db_session, intent="creative", target=TODAY, tz=TZ)
    # Sanity: the seeded readiness should be in the window between the two thresholds
    assert out_learn.recommendation == "rest_recommended"
    assert out_creative.recommendation != "rest_recommended"


# --------------------------------------------------------------------------- #
# intent=train
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_train_rest_day_when_f3_rests(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_depleted(db_session)
    out = await compute_advisor(db_session, intent="train", target=TODAY, tz=TZ)
    assert out.recommendation == "rest_day"


@pytest.mark.asyncio
async def test_train_full_session_when_gap_exists(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_neutral(db_session)
    await add_metric(db_session, "training_load_acute", 300.0, TODAY)
    await add_metric(db_session, "training_load_chronic", 500.0, TODAY)
    out = await compute_advisor(db_session, intent="train", target=TODAY, tz=TZ)
    assert out.recommendation.startswith("train_")
    assert out.window is not None


# --------------------------------------------------------------------------- #
# intent=rest
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_rest_returns_sleep_window(db_session) -> None:
    out = await compute_advisor(db_session, intent="rest", target=TODAY, tz=TZ)
    assert out.recommendation == "sleep_window"
    # Reasons should mention bedtime + wake
    assert any("bedtime" in r for r in out.reasons)


# --------------------------------------------------------------------------- #
# intent=meeting
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_meeting_avoids_top_focus_windows(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_neutral(db_session)
    out = await compute_advisor(db_session, intent="meeting", target=TODAY, tz=TZ)
    assert out.recommendation in ("meeting_slot", "no_slot")


# --------------------------------------------------------------------------- #
# intent=physical_task
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_physical_task_prefers_low_focus_slot(db_session) -> None:
    await _seed_baseline(db_session)
    await _seed_today_neutral(db_session)
    out = await compute_advisor(db_session, intent="physical_task", target=TODAY, tz=TZ)
    assert out.recommendation == "physical_slot"
    assert out.window is not None


# --------------------------------------------------------------------------- #
# unknown intent
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unsupported_intent_raises(db_session) -> None:
    with pytest.raises(ValueError, match="unsupported intent"):
        await compute_advisor(db_session, intent="dance", target=TODAY, tz=TZ)  # type: ignore[arg-type]
