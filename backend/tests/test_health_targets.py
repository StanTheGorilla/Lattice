"""V — AI-writable personalized health targets.

Invariants:
- A `default` seed never overwrites an `ai` row.
- Writes are clamped to per-age outer guardrails; the clamp note is appended
  to the rationale.
- `clear_target` falls back to the seed.
- F4 / sleep_debt read the store: changing it changes their behaviour.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.health_targets import (
    ALL_KINDS,
    CAFFEINE_BEDTIME_RESIDUAL_KIND,
    CAFFEINE_CUTOFF_HOUR_KIND,
    CAFFEINE_DAILY_CAP_KIND,
    SLEEP_CEILING_KIND,
    SLEEP_FLOOR_KIND,
    HealthTargetWrite,
    clear_target,
    get_target,
    outer_bounds,
    set_health_targets,
)
from lattice.functions.sleep_window import _healthy_sleep_bounds_min
from lattice.models import Profile

TZ = "Europe/Warsaw"


async def _set_age(session, age_years: int) -> None:
    today = datetime.now(ZoneInfo(TZ)).date()
    birthday = (today - timedelta(days=int(age_years * 365.25))).isoformat()
    profile = await session.get(Profile, 1)
    if profile is None:
        session.add(Profile(id=1, birthday=birthday))
    else:
        profile.birthday = birthday
    await session.commit()


# --------------------------------------------------------------------------- #
# Read path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_seed_fallback_matches_age_table(db_session) -> None:
    await _set_age(db_session, 16)
    floor = await get_target(db_session, SLEEP_FLOOR_KIND)
    ceil = await get_target(db_session, SLEEP_CEILING_KIND)
    seed_floor, seed_ceil = _healthy_sleep_bounds_min(16)
    assert floor.source == "default"
    assert ceil.source == "default"
    assert floor.value == seed_floor
    assert ceil.value == seed_ceil


@pytest.mark.asyncio
async def test_seed_caffeine_defaults_age_aware(db_session) -> None:
    await _set_age(db_session, 16)
    cap = await get_target(db_session, CAFFEINE_DAILY_CAP_KIND)
    assert cap.source == "default"
    assert cap.value == 100.0  # teen seed
    residual = await get_target(db_session, CAFFEINE_BEDTIME_RESIDUAL_KIND)
    assert residual.value == 50.0
    cutoff = await get_target(db_session, CAFFEINE_CUTOFF_HOUR_KIND)
    assert cutoff.value == 14.0


# --------------------------------------------------------------------------- #
# Write path + invariant
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_ai_write_wins_over_seed(db_session) -> None:
    await _set_age(db_session, 16)
    results = await set_health_targets(
        db_session,
        writes=[HealthTargetWrite(kind=SLEEP_FLOOR_KIND, value=510.0)],
        rationale="HRV trending low — raising floor",
    )
    assert len(results) == 1
    assert results[0].clamped is False
    assert results[0].stored == 510.0
    fetched = await get_target(db_session, SLEEP_FLOOR_KIND)
    assert fetched.source == "ai"
    assert fetched.value == 510.0


@pytest.mark.asyncio
async def test_clamp_to_outer_bounds_for_minor(db_session) -> None:
    await _set_age(db_session, 16)
    # Try to push daily caffeine cap to 800 mg — clamp to 200 mg teen ceiling.
    results = await set_health_targets(
        db_session,
        writes=[HealthTargetWrite(kind=CAFFEINE_DAILY_CAP_KIND, value=800.0)],
        rationale="testing clamp",
    )
    assert results[0].clamped is True
    assert results[0].stored == 200.0
    assert "clamped" in (results[0].rationale or "")
    fetched = await get_target(db_session, CAFFEINE_DAILY_CAP_KIND)
    assert fetched.value == 200.0
    assert fetched.source == "ai"


@pytest.mark.asyncio
async def test_clear_target_falls_back_to_seed(db_session) -> None:
    await _set_age(db_session, 16)
    await set_health_targets(
        db_session,
        writes=[HealthTargetWrite(kind=SLEEP_FLOOR_KIND, value=510.0)],
        rationale="raise",
    )
    await clear_target(db_session, kind=SLEEP_FLOOR_KIND)
    fetched = await get_target(db_session, SLEEP_FLOOR_KIND)
    assert fetched.source == "default"
    assert fetched.value == _healthy_sleep_bounds_min(16)[0]


def test_outer_bounds_widen_for_adults() -> None:
    teen_lo, teen_hi = outer_bounds(CAFFEINE_DAILY_CAP_KIND, 16)
    adult_lo, adult_hi = outer_bounds(CAFFEINE_DAILY_CAP_KIND, 30)
    assert teen_hi == 200.0
    assert adult_hi == 600.0
    assert teen_lo == adult_lo == 0.0


def test_all_kinds_have_bounds_for_unknown_age() -> None:
    for kind in ALL_KINDS:
        lo, hi = outer_bounds(kind, None)
        assert lo < hi
