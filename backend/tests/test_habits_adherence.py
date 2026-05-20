"""F8 — habit adherence tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from lattice.functions.habits_adherence import compute_habit_adherence
from tests.conftest import add_checkin, add_habit

TODAY = date(2026, 5, 14)


@pytest.mark.asyncio
async def test_current_streak_3_days(db_session) -> None:
    h = await add_habit(db_session, "meditate", target=7)
    for d in [TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=2)]:
        await add_checkin(db_session, h.id, d, completed=True)
    out = await compute_habit_adherence(
        db_session, from_=TODAY - timedelta(days=30), to=TODAY, today=TODAY,
    )
    item = out.items[0]
    assert item.current_streak_days == 3


@pytest.mark.asyncio
async def test_current_streak_broken(db_session) -> None:
    h = await add_habit(db_session, "meditate", target=7)
    await add_checkin(db_session, h.id, TODAY - timedelta(days=2), completed=True)
    # Today missing → current streak = 0
    out = await compute_habit_adherence(
        db_session, from_=TODAY - timedelta(days=30), to=TODAY, today=TODAY,
    )
    assert out.items[0].current_streak_days == 0


@pytest.mark.asyncio
async def test_longest_streak(db_session) -> None:
    h = await add_habit(db_session, "meditate", target=7)
    # 5-day streak that ended 2 weeks ago, plus a fresh 2-day streak
    for d in range(0, 5):
        await add_checkin(db_session, h.id, TODAY - timedelta(days=14 + d))
    for d in range(0, 2):
        await add_checkin(db_session, h.id, TODAY - timedelta(days=d))
    out = await compute_habit_adherence(
        db_session, from_=TODAY - timedelta(days=30), to=TODAY, today=TODAY,
    )
    item = out.items[0]
    assert item.longest_streak_days == 5
    assert item.current_streak_days == 2


@pytest.mark.asyncio
async def test_week_completion_pct_caps_at_100(db_session) -> None:
    # target=3, completed 5 of last 7 → 5/3 = 166% → capped 100
    h = await add_habit(db_session, "gym", target=3)
    for d in range(0, 5):
        await add_checkin(db_session, h.id, TODAY - timedelta(days=d))
    out = await compute_habit_adherence(
        db_session, from_=TODAY - timedelta(days=30), to=TODAY, today=TODAY,
    )
    item = next(i for i in out.items if i.name == "gym")
    assert item.week_completion_pct == 100.0


@pytest.mark.asyncio
async def test_inactive_habit_excluded(db_session) -> None:
    h1 = await add_habit(db_session, "active_one", target=7)
    h2 = await add_habit(db_session, "inactive_one", target=7)
    h2.active = False
    await db_session.commit()
    await add_checkin(db_session, h1.id, TODAY)
    await add_checkin(db_session, h2.id, TODAY)
    out = await compute_habit_adherence(
        db_session, from_=TODAY - timedelta(days=7), to=TODAY, today=TODAY,
    )
    names = {i.name for i in out.items}
    assert names == {"active_one"}
