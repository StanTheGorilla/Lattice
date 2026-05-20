"""Calendar sync — fetches Google events into `calendar_cache` with 5-min TTL.

Pure transform `event_to_row` converts a Google v3 event dict into the column
tuple stored on `calendar_cache`. The orchestrator `sync_window` calls
`list_events` on Google, UPSERTs each result, and reports how many rows
changed. `cached_events_or_refresh` reads the cache first and triggers a
refetch only when the freshest cached row is older than `TTL_MINUTES`.

Writes (`create_event_remote` / `patch_event_remote` / `delete_event_remote`)
push to Google immediately, then write-through the local cache so the next
read returns the updated state without a round-trip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.integrations.google_calendar import (
    GoogleCalendarClient,
    get_client,
)
from lattice.models import CalendarCache
from lattice.schemas.calendar import BusyInterval

logger = logging.getLogger(__name__)

TTL_MINUTES = 5


# --------------------------------------------------------------------------- #
# pure transforms
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class EventRow:
    google_event_id: str
    start: str
    end: str
    title: str
    description: str | None
    location: str | None
    is_all_day: bool


def event_to_row(event: dict[str, Any]) -> EventRow | None:
    """Convert a Google Calendar v3 event into a cache row.

    Returns None for events we cannot store (e.g. no id, cancelled, or
    missing start/end). All-day events have `date` (YYYY-MM-DD); timed
    events have `dateTime` (RFC3339 with offset).
    """
    event_id = event.get("id")
    status = event.get("status")
    if not event_id or status == "cancelled":
        return None

    start_block = event.get("start") or {}
    end_block = event.get("end") or {}

    is_all_day = "date" in start_block and "dateTime" not in start_block
    start = start_block.get("dateTime") or start_block.get("date")
    end = end_block.get("dateTime") or end_block.get("date")
    if not start or not end:
        return None

    title = event.get("summary") or "(no title)"
    description = event.get("description")
    location = event.get("location")

    return EventRow(
        google_event_id=event_id,
        start=start,
        end=end,
        title=title,
        description=description,
        location=location,
        is_all_day=is_all_day,
    )


def row_to_event_body(
    *,
    title: str,
    start: str,
    end: str,
    description: str | None,
    location: str | None,
    is_all_day: bool,
    timezone_name: str,
) -> dict[str, Any]:
    """Build the Google v3 insert/patch body from local fields."""
    if is_all_day:
        start_block = {"date": start}
        end_block = {"date": end}
    else:
        start_block = {"dateTime": start, "timeZone": timezone_name}
        end_block = {"dateTime": end, "timeZone": timezone_name}

    body: dict[str, Any] = {
        "summary": title,
        "start": start_block,
        "end": end_block,
    }
    if description is not None:
        body["description"] = description
    if location is not None:
        body["location"] = location
    return body


# --------------------------------------------------------------------------- #
# db helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _upsert(session: AsyncSession, rows: list[EventRow], fetched_at: str) -> int:
    if not rows:
        return 0
    values = [
        {
            "google_event_id": r.google_event_id,
            "start": r.start,
            "end": r.end,
            "title": r.title,
            "description": r.description,
            "location": r.location,
            "is_all_day": 1 if r.is_all_day else 0,
            "fetched_at": fetched_at,
        }
        for r in rows
    ]
    stmt = sqlite_insert(CalendarCache.__table__).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["google_event_id"],
        set_={
            "start": stmt.excluded.start,
            "end": stmt.excluded.end,
            "title": stmt.excluded.title,
            "description": stmt.excluded.description,
            "location": stmt.excluded.location,
            "is_all_day": stmt.excluded.is_all_day,
            "fetched_at": stmt.excluded.fetched_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def _cache_fresh(session: AsyncSession, time_min: str, time_max: str) -> bool:
    """True if at least one cached event overlaps the window and was fetched
    within `TTL_MINUTES`."""
    # Overlap: row.end >= time_min AND row.start <= time_max.
    overlap = and_(CalendarCache.end >= time_min, CalendarCache.start <= time_max)
    stmt = select(func.max(CalendarCache.fetched_at)).where(overlap)
    newest = (await session.execute(stmt)).scalar_one_or_none()
    if newest is None:
        return False
    try:
        newest_dt = datetime.fromisoformat(newest)
    except ValueError:
        return False
    age = datetime.now(UTC) - newest_dt
    return age < timedelta(minutes=TTL_MINUTES)


async def _cached_window(
    session: AsyncSession, time_min: str, time_max: str,
) -> list[CalendarCache]:
    stmt = (
        select(CalendarCache)
        .where(and_(CalendarCache.end >= time_min, CalendarCache.start <= time_max))
        .order_by(CalendarCache.start.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #


async def sync_window(
    session: AsyncSession,
    time_min: str,
    time_max: str,
    *,
    client: GoogleCalendarClient | None = None,
) -> int:
    """Fetch [time_min, time_max] from Google and UPSERT into cache.

    Returns the number of rows written.
    """
    client = client or get_client()
    events = await client.list_events(time_min=time_min, time_max=time_max)
    rows = [r for r in (event_to_row(e) for e in events) if r is not None]
    written = await _upsert(session, rows, _now_iso())
    logger.info(
        "calendar sync_window %s..%s — %d events written", time_min, time_max, written,
    )
    return written


async def cached_events_or_refresh(
    session: AsyncSession,
    time_min: str,
    time_max: str,
    *,
    client: GoogleCalendarClient | None = None,
) -> list[CalendarCache]:
    """Return cached rows; refetch from Google if cache is older than TTL."""
    if not await _cache_fresh(session, time_min, time_max):
        await sync_window(session, time_min, time_max, client=client)
    return await _cached_window(session, time_min, time_max)


async def free_busy(
    session: AsyncSession,
    time_min: str,
    time_max: str,
    *,
    client: GoogleCalendarClient | None = None,
) -> list[BusyInterval]:
    """Derive busy intervals from cached events (timed only — all-day excluded).

    All-day events are not considered "busy" for focus-window scoring; SPEC
    §6 F2 reads calendar busy intervals to subtract from the day, and an
    all-day "vacation" event would erase the whole day. Filter them out.
    """
    rows = await cached_events_or_refresh(session, time_min, time_max, client=client)
    return [
        BusyInterval(start=r.start, end=r.end)
        for r in rows
        if not r.is_all_day
    ]


async def create_event_remote(
    session: AsyncSession,
    body: dict[str, Any],
    *,
    client: GoogleCalendarClient | None = None,
) -> CalendarCache:
    """POST event to Google, then write-through to cache."""
    client = client or get_client()
    created = await client.create_event(body)
    row = event_to_row(created)
    if row is None:
        raise RuntimeError("Google returned an event we cannot cache")
    await _upsert(session, [row], _now_iso())
    return await _get_row_by_event_id(session, row.google_event_id)


async def patch_event_remote(
    session: AsyncSession,
    event_id: str,
    body: dict[str, Any],
    *,
    client: GoogleCalendarClient | None = None,
) -> CalendarCache:
    """PATCH event on Google, then write-through to cache."""
    client = client or get_client()
    updated = await client.patch_event(event_id, body)
    row = event_to_row(updated)
    if row is None:
        raise RuntimeError("Google returned an event we cannot cache")
    await _upsert(session, [row], _now_iso())
    return await _get_row_by_event_id(session, row.google_event_id)


async def delete_event_remote(
    session: AsyncSession,
    event_id: str,
    *,
    client: GoogleCalendarClient | None = None,
) -> None:
    """DELETE event on Google, then drop the cache row."""
    client = client or get_client()
    await client.delete_event(event_id)
    await session.execute(
        delete(CalendarCache).where(CalendarCache.google_event_id == event_id),
    )
    await session.commit()


async def prune_old_events(session: AsyncSession, *, older_than_days: int = 1) -> int:
    """Drop cached events whose end is more than N days in the past.

    SPEC §9 schedules `calendar_cache_prune` hourly; keep yesterday for the
    morning brief, drop anything earlier.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat(
        timespec="seconds",
    )
    result = await session.execute(
        delete(CalendarCache).where(CalendarCache.end < cutoff),
    )
    await session.commit()
    return int(result.rowcount or 0)


async def _get_row_by_event_id(
    session: AsyncSession, event_id: str,
) -> CalendarCache:
    stmt = select(CalendarCache).where(CalendarCache.google_event_id == event_id)
    row = (await session.execute(stmt)).scalar_one()
    return row


__all__ = [
    "EventRow",
    "TTL_MINUTES",
    "cached_events_or_refresh",
    "create_event_remote",
    "delete_event_remote",
    "event_to_row",
    "free_busy",
    "patch_event_remote",
    "prune_old_events",
    "row_to_event_body",
    "sync_window",
]
