"""Unit tests for sync.calendar_sync pure transforms."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.models import CalendarCache
from lattice.sync.calendar_sync import event_to_row, row_to_event_body, sync_window

# --------------------------------------------------------------------------- #
# event_to_row
# --------------------------------------------------------------------------- #


def test_event_to_row_timed_with_all_fields() -> None:
    event = {
        "id": "abc123",
        "status": "confirmed",
        "summary": "Standup",
        "description": "daily sync",
        "location": "Zoom",
        "start": {"dateTime": "2026-05-14T09:00:00+02:00", "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": "2026-05-14T09:15:00+02:00", "timeZone": "Europe/Warsaw"},
    }
    row = event_to_row(event)
    assert row is not None
    assert row.google_event_id == "abc123"
    assert row.title == "Standup"
    assert row.description == "daily sync"
    assert row.location == "Zoom"
    assert row.start == "2026-05-14T09:00:00+02:00"
    assert row.end == "2026-05-14T09:15:00+02:00"
    assert row.is_all_day is False


def test_event_to_row_all_day() -> None:
    event = {
        "id": "wholeday1",
        "status": "confirmed",
        "summary": "Vacation",
        "start": {"date": "2026-05-20"},
        "end": {"date": "2026-05-21"},
    }
    row = event_to_row(event)
    assert row is not None
    assert row.is_all_day is True
    assert row.start == "2026-05-20"
    assert row.end == "2026-05-21"
    assert row.description is None
    assert row.location is None


def test_event_to_row_no_summary_falls_back_to_placeholder() -> None:
    event = {
        "id": "noTitle",
        "status": "confirmed",
        "start": {"dateTime": "2026-05-14T10:00:00+02:00"},
        "end": {"dateTime": "2026-05-14T11:00:00+02:00"},
    }
    row = event_to_row(event)
    assert row is not None
    assert row.title == "(no title)"


def test_event_to_row_cancelled_returns_none() -> None:
    event = {
        "id": "deleted1",
        "status": "cancelled",
        "summary": "(was something)",
        "start": {"dateTime": "2026-05-14T10:00:00+02:00"},
        "end": {"dateTime": "2026-05-14T11:00:00+02:00"},
    }
    assert event_to_row(event) is None


def test_event_to_row_missing_id_returns_none() -> None:
    event = {
        "status": "confirmed",
        "summary": "Orphan",
        "start": {"dateTime": "2026-05-14T10:00:00+02:00"},
        "end": {"dateTime": "2026-05-14T11:00:00+02:00"},
    }
    assert event_to_row(event) is None


def test_event_to_row_missing_start_returns_none() -> None:
    event = {
        "id": "broken",
        "status": "confirmed",
        "summary": "Broken",
        "start": {},
        "end": {"dateTime": "2026-05-14T11:00:00+02:00"},
    }
    assert event_to_row(event) is None


# --------------------------------------------------------------------------- #
# row_to_event_body
# --------------------------------------------------------------------------- #


def test_row_to_event_body_timed_minimal() -> None:
    body = row_to_event_body(
        title="Focus",
        start="2026-05-14T10:00:00+02:00",
        end="2026-05-14T12:00:00+02:00",
        description=None,
        location=None,
        is_all_day=False,
        timezone_name="Europe/Warsaw",
    )
    assert body == {
        "summary": "Focus",
        "start": {"dateTime": "2026-05-14T10:00:00+02:00", "timeZone": "Europe/Warsaw"},
        "end": {"dateTime": "2026-05-14T12:00:00+02:00", "timeZone": "Europe/Warsaw"},
    }


def test_row_to_event_body_timed_with_extras() -> None:
    body = row_to_event_body(
        title="Standup",
        start="2026-05-14T09:00:00+02:00",
        end="2026-05-14T09:15:00+02:00",
        description="daily",
        location="Zoom",
        is_all_day=False,
        timezone_name="Europe/Warsaw",
    )
    assert body["description"] == "daily"
    assert body["location"] == "Zoom"


def test_row_to_event_body_all_day() -> None:
    body = row_to_event_body(
        title="Holiday",
        start="2026-05-20",
        end="2026-05-21",
        description=None,
        location=None,
        is_all_day=True,
        timezone_name="Europe/Warsaw",
    )
    assert body == {
        "summary": "Holiday",
        "start": {"date": "2026-05-20"},
        "end": {"date": "2026-05-21"},
    }


# --------------------------------------------------------------------------- #
# sync_window — reconciliation of Google-side deletions
# --------------------------------------------------------------------------- #


class _FakeClient:
    """Minimal stand-in returning a scripted event list per call."""

    def __init__(self, batches: list[list[dict[str, Any]]]) -> None:
        self._batches = batches
        self._i = 0

    async def list_events(
        self, *, time_min: str, time_max: str, calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        batch = self._batches[min(self._i, len(self._batches) - 1)]
        self._i += 1
        return batch


def _ev(event_id: str, summary: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "start": {"dateTime": "2026-06-05T08:20:00+02:00"},
        "end": {"dateTime": "2026-06-05T13:50:00+02:00"},
    }


WINDOW = ("2026-06-04T00:00:00+02:00", "2026-06-06T00:00:00+02:00")


async def _ids(session: AsyncSession) -> set[str]:
    rows = (await session.execute(select(CalendarCache.google_event_id))).scalars().all()
    return set(rows)


@pytest.mark.asyncio
async def test_sync_window_prunes_event_deleted_in_google(
    db_session: AsyncSession,
) -> None:
    """An event present in one fetch then gone in the next is removed from cache."""
    client = _FakeClient([
        [_ev("school", "Szkoła"), _ev("clatra", "Clatra")],
        [_ev("clatra", "Clatra")],  # school deleted directly in Google
    ])
    await sync_window(db_session, *WINDOW, client=client)
    assert await _ids(db_session) == {"school", "clatra"}

    await sync_window(db_session, *WINDOW, client=client)
    assert await _ids(db_session) == {"clatra"}


@pytest.mark.asyncio
async def test_sync_window_empty_fetch_clears_window(
    db_session: AsyncSession,
) -> None:
    """When Google returns nothing for the window, all overlapping rows drop."""
    client = _FakeClient([[_ev("school", "Szkoła")], []])
    await sync_window(db_session, *WINDOW, client=client)
    assert await _ids(db_session) == {"school"}

    await sync_window(db_session, *WINDOW, client=client)
    assert await _ids(db_session) == set()


@pytest.mark.asyncio
async def test_sync_window_keeps_events_outside_window(
    db_session: AsyncSession,
) -> None:
    """Reconciliation must not touch rows outside the synced window."""
    outside = {
        "id": "future",
        "status": "confirmed",
        "summary": "Far away",
        "start": {"dateTime": "2026-06-20T08:00:00+02:00"},
        "end": {"dateTime": "2026-06-20T09:00:00+02:00"},
    }
    far_window = ("2026-06-19T00:00:00+02:00", "2026-06-21T00:00:00+02:00")
    await sync_window(db_session, *far_window, client=_FakeClient([[outside]]))

    # Syncing a different, empty window leaves the far-away event intact.
    await sync_window(db_session, *WINDOW, client=_FakeClient([[]]))
    assert await _ids(db_session) == {"future"}
