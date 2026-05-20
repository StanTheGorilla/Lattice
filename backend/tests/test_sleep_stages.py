"""Unit tests for sleep-stage extraction + aggregate queries."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.sleep_pattern import (
    sleep_stages_for_night,
    sleep_stages_pattern,
)
from lattice.models import SleepStage
from lattice.sync.garmin_sync import extract_sleep_stages

TZ = "Europe/Warsaw"
DAY = date(2026, 5, 14)


def _utc_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# --------------------------------------------------------------------------- #
# extractor
# --------------------------------------------------------------------------- #


def test_extract_sleep_stages_from_levels_array() -> None:
    base = datetime(2026, 5, 13, 22, 0, tzinfo=ZoneInfo("UTC"))
    payload = {
        "sleepLevels": [
            {"startGMT": _utc_ms(base),                                  "endGMT": _utc_ms(base + timedelta(minutes=15)), "activityLevel": 1.0},  # light
            {"startGMT": _utc_ms(base + timedelta(minutes=15)),          "endGMT": _utc_ms(base + timedelta(minutes=90)), "activityLevel": 2.0},  # deep
            {"startGMT": _utc_ms(base + timedelta(minutes=90)),          "endGMT": _utc_ms(base + timedelta(minutes=120)), "activityLevel": 3.0},  # rem
            {"startGMT": _utc_ms(base + timedelta(minutes=120)),         "endGMT": _utc_ms(base + timedelta(minutes=125)), "activityLevel": 0.0},  # awake
            {"startGMT": _utc_ms(base + timedelta(minutes=125)),         "endGMT": _utc_ms(base + timedelta(minutes=180)), "activityLevel": 1.0},  # light
        ],
    }
    rows = extract_sleep_stages(payload, DAY, TZ)
    assert len(rows) == 5
    stages = [r.stage for r in rows]
    assert stages == ["light", "deep", "rem", "awake", "light"]
    assert rows[1].duration_min == 75.0
    assert rows[3].duration_min == 5.0
    # All rows tagged with wake day.
    assert all(r.night_date == "2026-05-14" for r in rows)
    # Each timestamp in local TZ.
    assert "+02:00" in rows[0].start


def test_extract_sleep_stages_handles_string_levels() -> None:
    base_iso = "2026-05-13T22:00:00.0"
    end_iso = "2026-05-13T22:30:00.0"
    payload = {
        "sleepLevels": [
            {"startGMT": base_iso, "endGMT": end_iso, "activityLevel": "deep"},
        ],
    }
    rows = extract_sleep_stages(payload, DAY, TZ)
    assert len(rows) == 1
    assert rows[0].stage == "deep"
    assert rows[0].duration_min == 30.0


def test_extract_sleep_stages_skips_bad_rows() -> None:
    payload = {
        "sleepLevels": [
            {"startGMT": "bogus", "endGMT": "bogus", "activityLevel": 1.0},
            {"startGMT": _utc_ms(datetime(2026, 5, 13, 22, 0, tzinfo=ZoneInfo("UTC"))),
             "endGMT":   _utc_ms(datetime(2026, 5, 13, 22, 0, tzinfo=ZoneInfo("UTC"))),  # zero duration
             "activityLevel": 1.0},
            {"startGMT": _utc_ms(datetime(2026, 5, 13, 22, 0, tzinfo=ZoneInfo("UTC"))),
             "endGMT":   _utc_ms(datetime(2026, 5, 13, 22, 10, tzinfo=ZoneInfo("UTC"))),
             "activityLevel": 99.0},  # unknown level
        ],
    }
    rows = extract_sleep_stages(payload, DAY, TZ)
    assert rows == []


def test_extract_sleep_stages_empty() -> None:
    assert extract_sleep_stages(None, DAY, TZ) == []
    assert extract_sleep_stages({}, DAY, TZ) == []
    assert extract_sleep_stages({"sleepLevels": []}, DAY, TZ) == []


# --------------------------------------------------------------------------- #
# db-backed aggregate queries
# --------------------------------------------------------------------------- #


def _add_stage(
    session: AsyncSession,
    *, night: str, start: datetime, dur_min: float, stage: str,
) -> None:
    end = start + timedelta(minutes=dur_min)
    session.add(SleepStage(
        night_date=night,
        start=start.isoformat(),
        end=end.isoformat(),
        stage=stage,
        duration_min=dur_min,
    ))


@pytest.mark.asyncio
async def test_sleep_stages_for_night_returns_timeline(db_session: AsyncSession) -> None:
    night = "2026-05-14"
    start = datetime(2026, 5, 13, 22, 0, tzinfo=ZoneInfo(TZ))
    _add_stage(db_session, night=night, start=start, dur_min=15, stage="light")
    _add_stage(db_session, night=night, start=start + timedelta(minutes=15), dur_min=60, stage="deep")
    _add_stage(db_session, night=night, start=start + timedelta(minutes=75), dur_min=30, stage="rem")
    _add_stage(db_session, night=night, start=start + timedelta(minutes=105), dur_min=5, stage="awake")
    await db_session.commit()

    out = await sleep_stages_for_night(db_session, night)
    assert out["n_segments"] == 4
    assert out["totals_min"] == {"awake": 5.0, "light": 15.0, "deep": 60.0, "rem": 30.0}
    assert out["wake_events"] == 1
    assert out["segments"][0]["stage"] == "light"
    assert out["segments"][-1]["stage"] == "awake"


@pytest.mark.asyncio
async def test_sleep_stages_pattern_aggregates(db_session: AsyncSession) -> None:
    # Seed 6 nights. Each night: light 30 → deep 60 → rem 30, with a small wake gap.
    # First deep should appear ~30 min after onset every night.
    for i in range(6):
        night_date = (date(2026, 5, 10) + timedelta(days=i)).isoformat()
        onset = datetime(2026, 5, 9 + i, 22, 0, tzinfo=ZoneInfo(TZ))
        _add_stage(db_session, night=night_date, start=onset, dur_min=30, stage="light")
        _add_stage(db_session, night=night_date, start=onset + timedelta(minutes=30), dur_min=60, stage="deep")
        _add_stage(db_session, night=night_date, start=onset + timedelta(minutes=90), dur_min=30, stage="rem")
        _add_stage(db_session, night=night_date, start=onset + timedelta(minutes=120), dur_min=2, stage="awake")
    await db_session.commit()

    out = await sleep_stages_pattern(
        db_session, from_iso="2026-05-10", to_iso="2026-05-15",
    )
    assert out["n_nights"] == 6
    assert out["low_confidence"] is False
    assert out["stages"]["deep"]["median_min"] == 60.0
    assert out["stages"]["rem"]["median_min"] == 30.0
    # First deep at 30 min after onset every night.
    assert out["stages"]["deep"]["median_first_offset_min"] == 30.0
    assert out["stages"]["rem"]["median_first_offset_min"] == 90.0
    assert out["median_rem_cycles_per_night"] == 1.0
    assert out["median_wake_events_per_night"] == 1.0


@pytest.mark.asyncio
async def test_sleep_stages_pattern_empty(db_session: AsyncSession) -> None:
    out = await sleep_stages_pattern(
        db_session, from_iso="2026-05-10", to_iso="2026-05-15",
    )
    assert out["n_nights"] == 0
    assert out["low_confidence"] is True
