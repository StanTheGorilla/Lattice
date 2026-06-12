"""F4 sleep-window tests.

Cover the prescriptive duration model: an age-appropriate healthy envelope,
positioned inside by a recovery-debt fraction built from every Garmin signal,
nudged by today's acute recovery, and made actionable by the feasibility switch
that flips to "best achievable now" once you're past the ideal bedtime.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.sleep_window import (
    _age_on,
    _healthy_sleep_bounds_min,
    compute_sleep_window,
)
from lattice.models import Profile

from .conftest import add_metric

TZ = "Europe/Warsaw"
TARGET = date(2026, 6, 3)
# wake for TARGET (no calendar event) is 2026-06-04 08:00; this is comfortably
# after it, so the feasibility switch stays off and the headline is the ideal.
NOW_AFTER = datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo(TZ))


def _at(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(TZ))


async def _set_profile(session: Any, **fields: Any) -> None:
    session.add(Profile(id=1, **fields))
    await session.commit()


async def _seed(session: Any, name: str, value: float, day: date) -> None:
    await add_metric(session, name, value, day, tz=TZ)


async def _seed_recent(session: Any, name: str, value: float, n: int = 7) -> None:
    """`n` nights of `name`=value ending the night before TARGET."""
    for i in range(1, n + 1):
        await _seed(session, name, value, TARGET - timedelta(days=i))


# --------------------------------------------------------------------------- #
# Age helpers
# --------------------------------------------------------------------------- #


def test_age_on_before_and_after_birthday() -> None:
    assert _age_on("2009-09-21", date(2026, 6, 3)) == 16  # birthday not yet reached
    assert _age_on("2009-05-01", date(2026, 6, 3)) == 17  # birthday already passed
    assert _age_on(None, date(2026, 6, 3)) is None
    assert _age_on("garbage", date(2026, 6, 3)) is None


def test_healthy_bounds_by_age() -> None:
    assert _healthy_sleep_bounds_min(16) == (480.0, 600.0)  # teen 8–10h
    assert _healthy_sleep_bounds_min(40) == (420.0, 540.0)  # adult 7–9h
    assert _healthy_sleep_bounds_min(70) == (420.0, 480.0)  # senior 7–8h
    assert _healthy_sleep_bounds_min(None) == (420.0, 540.0)  # unknown → adult


# --------------------------------------------------------------------------- #
# Healthy envelope + neutral default
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_no_data_uses_mid_adult_range(db_session: Any) -> None:
    """No profile, no metrics → neutral debt 0.5 → midpoint of adult 7–9h."""
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 480.0  # (420+540)/2
    assert out.inputs["n_recovery_signals"] == 0
    assert out.inputs["recovery_debt_fraction"] == 0.5
    assert out.inputs["age"] is None
    assert out.inputs["feasible"] is True
    assert any("limited recovery history" in f for f in out.flags)


@pytest.mark.asyncio
async def test_teen_no_data_uses_mid_teen_range(db_session: Any) -> None:
    """16y/o with no history → midpoint of the teen 8–10h range (9h)."""
    await _set_profile(db_session, birthday="2009-09-21")
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 540.0  # (480+600)/2
    assert out.inputs["age"] == 16
    assert out.inputs["healthy_floor_min"] == 480
    assert out.inputs["healthy_ceiling_min"] == 600


# --------------------------------------------------------------------------- #
# Recovery-debt positioning inside the envelope
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_chronic_sleep_debt_pushes_toward_ceiling(db_session: Any) -> None:
    """A week averaging 6h (2h below the 8h floor) saturates debt → ceiling."""
    await _set_profile(db_session, birthday="2009-09-21")
    await _seed_recent(db_session, "sleep_duration_min", 360.0)  # 6h nightly
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 600.0  # teen ceiling
    assert out.inputs["recovery_debt_fraction"] == 1.0
    assert out.inputs["recent_sleep_mean_min"] == 360
    assert out.inputs["n_recovery_signals"] == 1
    assert any("recent sleep 6h00m below 8h00m floor" in f for f in out.flags)


@pytest.mark.asyncio
async def test_well_rested_sleep_sits_at_floor(db_session: Any) -> None:
    """A week at/above the floor → no sleep debt → target the healthy floor."""
    await _set_profile(db_session, birthday="2009-09-21")
    await _seed_recent(db_session, "sleep_duration_min", 540.0)  # 9h nightly
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 480.0  # teen floor
    assert out.inputs["recovery_debt_fraction"] == 0.0


@pytest.mark.asyncio
async def test_depleted_markers_push_toward_ceiling(db_session: Any) -> None:
    """Recent HRV well below the user's own baseline → depleted → ceiling."""
    await _set_profile(db_session, birthday="2009-09-21")
    for i in range(8, 31):  # older baseline: high HRV
        await _seed(db_session, "hrv_overnight_avg", 60.0, TARGET - timedelta(days=i))
    await _seed_recent(db_session, "hrv_overnight_avg", 40.0)  # recent: low HRV
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 600.0
    assert out.inputs["recovery_debt_fraction"] == 1.0
    assert any("recovery below baseline (HRV)" in f for f in out.flags)


@pytest.mark.asyncio
async def test_strong_markers_sit_at_floor(db_session: Any) -> None:
    """Recent HRV well above baseline → recovered → target the floor."""
    await _set_profile(db_session, birthday="2009-09-21")
    for i in range(8, 31):  # older baseline: low HRV
        await _seed(db_session, "hrv_overnight_avg", 40.0, TARGET - timedelta(days=i))
    await _seed_recent(db_session, "hrv_overnight_avg", 60.0)  # recent: high HRV
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 480.0
    assert out.inputs["recovery_debt_fraction"] == 0.0
    assert any("recovery strong (HRV)" in f for f in out.flags)


# --------------------------------------------------------------------------- #
# Acute (today's state) nudge
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_acute_bad_day_adds_sleep(db_session: Any) -> None:
    """High stress + low body battery today → +30 min on top of the base.

    Uses stress_avg + body_battery_min (acute-only signals, not part of the
    chronic debt model) so the base stays at the neutral midpoint.
    """
    for i in range(1, 15):  # 14-day baselines (mean≈center, sd>0)
        day = TARGET - timedelta(days=i)
        await _seed(db_session, "stress_avg", 30.0 + (i % 3 - 1) * 2.0, day)
        await _seed(db_session, "body_battery_min", 50.0 + (i % 3 - 1) * 2.0, day)
    await _seed(db_session, "stress_avg", 60.0, TARGET)  # +σ saturated
    await _seed(db_session, "body_battery_min", 10.0, TARGET)

    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 510.0  # adult midpoint 480 + 30
    assert out.inputs["acute_adjustment_min"] == 30
    assert out.inputs["within_range_target_min"] == 480
    basis = out.inputs["acute_basis"]
    assert isinstance(basis, str)
    assert "elevated stress" in basis and "low body battery" in basis
    assert any("for today's recovery" in f for f in out.flags)


# --------------------------------------------------------------------------- #
# Profile override
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_profile_target_overrides_but_clamps(db_session: Any) -> None:
    """An explicit 11h profile target is honored but clamped to the teen 10h."""
    await _set_profile(db_session, birthday="2009-09-21", target_sleep_min=660)
    out = await compute_sleep_window(db_session, target=TARGET, tz=TZ, now=NOW_AFTER)
    assert out.target_duration_min == 600.0
    assert out.inputs["profile_target_used"] is True
    assert any("using your configured target 11h00m" in f for f in out.flags)


# --------------------------------------------------------------------------- #
# Feasibility — "best achievable now"
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_before_ideal_bedtime_shows_ideal(db_session: Any) -> None:
    """Opened at 22:00, ideal bedtime 23:00 → on time, show the full window."""
    await _set_profile(db_session, birthday="2009-09-21")  # 9h → ideal 23:00
    out = await compute_sleep_window(
        db_session, target=TARGET, tz=TZ, now=_at(2026, 6, 3, 22, 0),
    )
    assert out.target_duration_min == 540.0
    assert out.inputs["feasible"] is True
    assert out.bedtime.endswith("23:00:00+02:00")


@pytest.mark.asyncio
async def test_past_ideal_bedtime_switches_to_achievable(db_session: Any) -> None:
    """Opened at 23:30 with a 23:00 ideal → sleep now, 8h30m before 08:00."""
    await _set_profile(db_session, birthday="2009-09-21")
    out = await compute_sleep_window(
        db_session, target=TARGET, tz=TZ, now=_at(2026, 6, 3, 23, 30),
    )
    assert out.inputs["feasible"] is False
    assert out.target_duration_min == 510.0  # 08:00 − 23:30
    assert out.inputs["minutes_past_ideal_bedtime"] == 30
    assert out.inputs["achievable_duration_min"] == 510
    assert out.inputs["target_duration_min"] == 540  # ideal kept as secondary
    assert out.bedtime.endswith("23:30:00+02:00")
    assert any("past ideal bedtime 23:00" in f for f in out.flags)


@pytest.mark.asyncio
async def test_after_midnight_switches_to_achievable(db_session: Any) -> None:
    """The classic case: opened at 00:30, sleeping now gives 7h30m before wake."""
    await _set_profile(db_session, birthday="2009-09-21")
    out = await compute_sleep_window(
        db_session, target=TARGET, tz=TZ, now=_at(2026, 6, 4, 0, 30),
    )
    assert out.inputs["feasible"] is False
    assert out.target_duration_min == 450.0  # 08:00 − 00:30
    assert out.bedtime.endswith("00:30:00+02:00")
