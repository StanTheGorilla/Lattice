"""Shared pytest fixtures for backend tests.

`db_session` provides an isolated in-memory SQLite session with all tables
created from the ORM metadata. Each test gets a fresh session/db.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lattice.models import (
    Base,
    CalendarCache,
    Entry,
    HabitCheckin,
    HabitDefinition,
    Metric,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session
    await engine.dispose()


def midnight(day: date, tz: str = "Europe/Warsaw") -> str:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(tz)).isoformat()


async def add_metric(
    session: AsyncSession,
    name: str,
    value: float,
    day: date,
    *,
    tz: str = "Europe/Warsaw",
    unit: str | None = None,
    source: str = "garmin",
) -> Metric:
    row = Metric(
        timestamp=midnight(day, tz),
        metric_name=name,
        value=value,
        unit=unit,
        source=source,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def add_calendar_event(
    session: AsyncSession,
    *,
    event_id: str,
    start: datetime,
    end: datetime,
    title: str = "Meeting",
    is_all_day: bool = False,
) -> CalendarCache:
    row = CalendarCache(
        google_event_id=event_id,
        start=start.isoformat(),
        end=end.isoformat(),
        title=title,
        description=None,
        location=None,
        is_all_day=1 if is_all_day else 0,
        fetched_at=datetime.now(start.tzinfo or ZoneInfo("UTC")).isoformat(),
    )
    session.add(row)
    await session.commit()
    return row


async def add_entry(
    session: AsyncSession,
    *,
    entry_type: str,
    data: dict,
    when: datetime,
    source: str = "web",
) -> Entry:
    row = Entry(
        timestamp=when.isoformat(),
        logged_at=when.isoformat(),
        type=entry_type,
        data=json.dumps(data),
        source=source,
    )
    session.add(row)
    await session.commit()
    return row


async def add_habit(
    session: AsyncSession,
    name: str,
    target: int = 7,
    *,
    created: datetime | None = None,
) -> HabitDefinition:
    row = HabitDefinition(
        name=name,
        target_per_week=target,
        active=True,
        created_at=(created or datetime.now(ZoneInfo("UTC"))).isoformat(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def add_checkin(
    session: AsyncSession,
    habit_id: int,
    day: date,
    completed: bool = True,
) -> HabitCheckin:
    row = HabitCheckin(
        habit_id=habit_id,
        date=day.isoformat(),
        completed=completed,
        note=None,
    )
    session.add(row)
    await session.commit()
    return row


__all__ = [
    "add_calendar_event",
    "add_checkin",
    "add_entry",
    "add_habit",
    "add_metric",
    "db_session",
    "midnight",
]
