"""Pydantic schemas for the `calendar_cache` table and its endpoints (SPEC §5.4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CalendarEvent(BaseModel):
    """Mirrors a `calendar_cache` row, plus the original google_event_id."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    google_event_id: str
    start: str
    end: str
    title: str
    description: str | None = None
    location: str | None = None
    is_all_day: bool
    fetched_at: str


class CalendarEventCreate(BaseModel):
    title: str
    start: str = Field(description="RFC3339 with offset for timed; YYYY-MM-DD for all-day")
    end: str
    description: str | None = None
    location: str | None = None
    is_all_day: bool = False


class CalendarEventPatch(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None
    is_all_day: bool | None = None


class BusyInterval(BaseModel):
    start: str
    end: str


class CalendarSyncResult(BaseModel):
    refreshed: int
    window_from: str
    window_to: str
