"""Tests for P1-1 local-offset normalization of event timestamps.

Entry/log_entry writes are normalized to the configured local offset so they
sort correctly against the local-anchored cutoffs every functions/ query
builds. Without this, a UTC-stored evening entry falls outside a local "today"
window because the offset-bearing ISO strings compare wrong lexicographically.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from lattice.utils import normalize_to_local_iso

TZ = "Europe/Warsaw"


def test_utc_string_converted_to_local_offset() -> None:
    # 21:30Z in summer Warsaw (+02:00) is 23:30 local.
    out = normalize_to_local_iso("2026-06-12T21:30:00+00:00", tz=TZ)
    dt = datetime.fromisoformat(out)
    assert dt.utcoffset() == ZoneInfo(TZ).utcoffset(dt)
    assert dt.hour == 23
    assert dt.minute == 30


def test_naive_string_assumed_local() -> None:
    out = normalize_to_local_iso("2026-06-12T23:30:00", tz=TZ)
    dt = datetime.fromisoformat(out)
    assert dt.tzinfo is not None
    assert dt.hour == 23


def test_already_local_unchanged_instant() -> None:
    src = "2026-06-12T23:30:00+02:00"
    out = normalize_to_local_iso(src, tz=TZ)
    assert datetime.fromisoformat(out) == datetime.fromisoformat(src)


def test_malformed_returned_unchanged() -> None:
    assert normalize_to_local_iso("not-a-date", tz=TZ) == "not-a-date"


def test_normalized_evening_sorts_inside_local_day() -> None:
    # The bug this guards: a UTC evening entry must still sort >= local midnight.
    midnight = datetime(2026, 6, 12, 0, 0, tzinfo=ZoneInfo(TZ)).isoformat()
    stored = normalize_to_local_iso("2026-06-12T21:30:00+00:00", tz=TZ)
    assert stored >= midnight  # lexicographic, same offset family
