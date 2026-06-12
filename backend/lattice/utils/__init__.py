"""Small utilities — TZ-aware datetime helpers, etc."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from lattice.config import settings


def normalize_to_local_iso(value: str, *, tz: str | None = None) -> str:
    """Return *value* re-expressed in the configured local-TZ offset.

    P1-1: Entry/Metric/Workout timestamps are compared **lexicographically** in
    SQL against cutoffs that every `functions/` query builds in the configured
    local timezone (``datetime.combine(day, …, tzinfo=ZoneInfo(tz))``). For that
    comparison to be correct, the stored rows must share the same offset family.
    Historically `create_entry` / the `log_entry` tool defaulted to
    ``datetime.now(UTC)`` while client-supplied timestamps could carry any
    offset, so a Warsaw entry at 23:30 local stored as ``21:30Z`` fell outside a
    ``…T00:00:00+02:00`` "today" cutoff. Normalizing every write to the local
    offset removes the mixed-offset hazard without a historical data migration.

    A naive string (no offset) is assumed to already be in local time. An
    unparseable string is returned unchanged so a malformed client value never
    raises on the write path (the row is still stored, just not normalized).
    """
    zone = ZoneInfo(tz or settings.timezone)
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(zone).isoformat()


__all__ = ["normalize_to_local_iso"]
