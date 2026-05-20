"""F5 — caffeine cutoff tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.caffeine import compute_caffeine_status
from tests.conftest import add_entry

TZ = "Europe/Warsaw"
ZONE = ZoneInfo(TZ)
TODAY = date(2026, 5, 14)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TODAY, time(hour=hour, minute=minute), tzinfo=ZONE)


def bed_at_23() -> datetime:
    return datetime.combine(TODAY, time(hour=23), tzinfo=ZONE)


@pytest.mark.asyncio
async def test_no_cups_safe_for_new(db_session) -> None:
    out = await compute_caffeine_status(
        db_session, at=at(8), tz=TZ, bedtime_override=bed_at_23(),
    )
    assert out.residual_at_bedtime_mg == 0.0
    assert out.safe_for_new_cup is True
    assert out.last_call_minutes is not None


@pytest.mark.asyncio
async def test_residual_decays_correctly(db_session) -> None:
    # One cup (80mg) at 18:00. Bedtime 23:00 → 5h away → 1 half-life → 40mg.
    await add_entry(
        db_session, entry_type="drink",
        data={"kind": "coffee", "count": 1}, when=at(18),
    )
    out = await compute_caffeine_status(
        db_session, at=at(19), tz=TZ, bedtime_override=bed_at_23(),
    )
    assert abs(out.residual_at_bedtime_mg - 40.0) < 0.5


@pytest.mark.asyncio
async def test_too_much_caffeine_no_new_cup(db_session) -> None:
    # Heavy load: 3 cups at 20:00 → very high residual at 23:00.
    await add_entry(
        db_session, entry_type="drink",
        data={"kind": "coffee", "count": 3}, when=at(20),
    )
    out = await compute_caffeine_status(
        db_session, at=at(20, 30), tz=TZ, bedtime_override=bed_at_23(),
    )
    assert out.safe_for_new_cup is False
    assert out.last_call_minutes is None


@pytest.mark.asyncio
async def test_non_coffee_drink_ignored(db_session) -> None:
    await add_entry(
        db_session, entry_type="drink",
        data={"kind": "water", "volume_ml": 500}, when=at(15),
    )
    out = await compute_caffeine_status(
        db_session, at=at(15), tz=TZ, bedtime_override=bed_at_23(),
    )
    assert out.residual_at_bedtime_mg == 0.0
