"""Unit tests for sync.calendar_sync pure transforms."""

from __future__ import annotations

from lattice.sync.calendar_sync import event_to_row, row_to_event_body

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
