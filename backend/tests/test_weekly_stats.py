"""Weekly Stats (F7 Stage A) tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.weekly_stats import (
    CORR_MIN_N,
    CORR_R_THRESHOLD,
    MEAN_SHIFT_SD_THRESHOLD,
    compute_weekly_stats,
    iso_week_bounds,
)

from .conftest import add_calendar_event, add_entry, add_habit, add_checkin, add_metric

TZ = "Europe/Warsaw"


def _ts(day: date, hour: int = 12, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(TZ))


def test_iso_week_bounds_simple() -> None:
    # 2026-05-13 is a Wednesday → ISO week 20.
    mon, sun, label = iso_week_bounds(date(2026, 5, 13))
    assert mon == date(2026, 5, 11)
    assert sun == date(2026, 5, 17)
    assert label == "2026-W20"


def test_iso_week_bounds_year_boundary() -> None:
    # 2026-01-01 is a Thursday → ISO week 1 (Mon 2025-12-29 → Sun 2026-01-04).
    mon, sun, label = iso_week_bounds(date(2026, 1, 1))
    assert mon == date(2025, 12, 29)
    assert sun == date(2026, 1, 4)
    assert label == "2026-W01"


@pytest.mark.asyncio
async def test_daily_aggregates_and_averages(db_session) -> None:
    """7 days of sleep_score seeded → averages and daily list reflect them."""
    monday = date(2026, 5, 11)
    sunday = monday + timedelta(days=6)
    sleep_scores = [70, 75, 80, 65, 90, 72, 78]
    for i, score in enumerate(sleep_scores):
        await add_metric(db_session, "sleep_score", float(score), monday + timedelta(days=i))
    out = await compute_weekly_stats(db_session, target=date(2026, 5, 13), tz=TZ)
    assert out.iso_week == "2026-W20"
    assert out.week_start == monday.isoformat()
    assert out.week_end == sunday.isoformat()
    assert len(out.daily) == 7
    expected_mean = round(sum(sleep_scores) / 7, 2)
    assert out.averages["sleep_score"] == expected_mean


@pytest.mark.asyncio
async def test_best_and_worst_day(db_session) -> None:
    """Readiness varies day-to-day; best/worst should track the extremes."""
    monday = date(2026, 5, 11)
    # Seed enough components so on-the-fly compute_readiness produces real scores
    # for two specific days only.
    for d_off, sleep, hrv, rhr, bb, stress in (
        (0, 90, 70, 50, 95, 20),   # very good
        (3, 40, 35, 70, 30, 80),   # very bad
    ):
        target = monday + timedelta(days=d_off)
        await add_metric(db_session, "sleep_score", float(sleep), target)
        await add_metric(db_session, "hrv_overnight_avg", float(hrv), target)
        await add_metric(db_session, "resting_hr", float(rhr), target)
        await add_metric(db_session, "body_battery_start", float(bb), target)
        await add_metric(db_session, "stress_avg", float(stress), target - timedelta(days=1))
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    assert out.best_day is not None
    assert out.worst_day is not None
    assert out.best_day.date == monday.isoformat()
    assert out.worst_day.date == (monday + timedelta(days=3)).isoformat()
    assert out.best_day.readiness > out.worst_day.readiness


@pytest.mark.asyncio
async def test_correlation_threshold_filters_weak_signal(db_session) -> None:
    """A weak random correlation should NOT be reported."""
    monday = date(2026, 5, 11)
    # Seed coffee at a random hour each day + sleep_score next day with no relation.
    coffees = [(0, 9, 80), (1, 14, 75), (2, 11, 78), (3, 16, 76), (4, 8, 81), (5, 12, 79)]
    for d_off, hour, next_sleep in coffees:
        coffee_day = monday + timedelta(days=d_off)
        await add_entry(
            db_session,
            entry_type="drink",
            data={"kind": "coffee", "count": 1},
            when=_ts(coffee_day, hour=hour),
        )
        await add_metric(
            db_session, "sleep_score", float(next_sleep),
            coffee_day + timedelta(days=1),
        )
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    # No correlation should be flagged — noisy data, |r| likely below 0.5.
    cafs = [c for c in out.correlations if "caffeine" in c.label]
    if cafs:
        assert abs(cafs[0].r) >= CORR_R_THRESHOLD
        assert cafs[0].n >= CORR_MIN_N


@pytest.mark.asyncio
async def test_correlation_strong_signal_is_reported(db_session) -> None:
    """A near-perfect inverse caffeine_time × sleep_score relation should fire."""
    monday = date(2026, 5, 11)
    # Later coffee → worse sleep, almost linearly.
    pairs = [(0, 8, 90), (1, 10, 85), (2, 12, 78), (3, 14, 70), (4, 16, 62), (5, 18, 55)]
    for d_off, hour, next_sleep in pairs:
        coffee_day = monday + timedelta(days=d_off)
        await add_entry(
            db_session,
            entry_type="drink",
            data={"kind": "coffee", "count": 1},
            when=_ts(coffee_day, hour=hour),
        )
        await add_metric(
            db_session, "sleep_score", float(next_sleep),
            coffee_day + timedelta(days=1),
        )
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    cafs = [c for c in out.correlations if "caffeine" in c.label]
    assert len(cafs) == 1
    assert cafs[0].direction == "negative"
    assert cafs[0].r < -CORR_R_THRESHOLD
    assert cafs[0].n >= CORR_MIN_N


@pytest.mark.asyncio
async def test_mean_shift_flag_fires_above_one_sd(db_session) -> None:
    """Trailing baseline = ~50; this week sustained ~80 → > 1 SD up."""
    monday = date(2026, 5, 11)
    # Trailing 4 weeks (28 days before monday) at ~50 ± 2.
    trailing_start = monday - timedelta(days=28)
    baseline_values = [48, 51, 49, 52, 47, 53, 50, 49, 51, 48, 50, 52,
                       49, 51, 47, 52, 48, 50, 51, 49, 53, 49, 50, 51,
                       48, 50, 52, 49]
    for i, v in enumerate(baseline_values):
        await add_metric(db_session, "sleep_score", float(v), trailing_start + timedelta(days=i))
    # This week: all 80s
    for i in range(7):
        await add_metric(db_session, "sleep_score", 80.0, monday + timedelta(days=i))
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    shifts = [m for m in out.mean_shifts if m.metric == "sleep_score"]
    assert len(shifts) == 1
    assert shifts[0].direction == "up"
    assert shifts[0].delta_sd > MEAN_SHIFT_SD_THRESHOLD


@pytest.mark.asyncio
async def test_mean_shift_does_not_fire_within_one_sd(db_session) -> None:
    """Steady values (trailing ≈ this week) → no shift flagged."""
    monday = date(2026, 5, 11)
    trailing_start = monday - timedelta(days=28)
    for i in range(28):
        await add_metric(db_session, "sleep_score", 70.0 + (i % 3), trailing_start + timedelta(days=i))
    for i in range(7):
        await add_metric(db_session, "sleep_score", 71.0, monday + timedelta(days=i))
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    shifts = [m for m in out.mean_shifts if m.metric == "sleep_score"]
    assert shifts == []


@pytest.mark.asyncio
async def test_habits_appear_with_completed_count(db_session) -> None:
    monday = date(2026, 5, 11)
    h = await add_habit(db_session, "meditate", target=5)
    for d_off in (0, 1, 3):  # 3 checkins this week
        await add_checkin(db_session, h.id, monday + timedelta(days=d_off))
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    assert len(out.habits) == 1
    assert out.habits[0].name == "meditate"
    assert out.habits[0].target_per_week == 5
    # F8's week_completion_pct caps at 100 — 3 of 5 = 60.
    assert out.habits[0].week_completion_pct == 60.0


@pytest.mark.asyncio
async def test_meetings_vs_energy_requires_min_n(db_session) -> None:
    """Only 2 days of paired data → no correlation should be returned."""
    monday = date(2026, 5, 11)
    for d_off, mt_hours, en_score in ((0, 2, 4), (1, 6, 2)):
        day = monday + timedelta(days=d_off)
        await add_calendar_event(
            db_session,
            event_id=f"e{d_off}a",
            start=_ts(day, 10),
            end=_ts(day, 10 + mt_hours),
            title="Meeting",
        )
        await add_entry(
            db_session, entry_type="energy", data={"score": en_score}, when=_ts(day, 18),
        )
    out = await compute_weekly_stats(db_session, target=monday, tz=TZ)
    assert all("meeting" not in c.label for c in out.correlations)
