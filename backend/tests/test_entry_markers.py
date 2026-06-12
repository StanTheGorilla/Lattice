"""Tests for functions/entry_markers.py (P2-2)."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.entry_markers import compute_entry_markers
from lattice.models import Entry

TZ = "Europe/Warsaw"


async def _add_entry(session, entry_type: str, data: dict, when: datetime) -> int:
    row = Entry(
        timestamp=when.isoformat(),
        logged_at=when.isoformat(),
        type=entry_type,
        data=json.dumps(data),
        source="web",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row.id


def _labels(out: dict) -> set[str]:
    return {m["label"] for m in out["markers"]}


@pytest.mark.asyncio
async def test_not_found(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await compute_entry_markers(db_session, 999, TZ)
    assert out["error"] == "not_found"


@pytest.mark.asyncio
async def test_caffeinated_drink_has_caffeine_chip(db_session) -> None:  # type: ignore[no-untyped-def]
    when = datetime(2026, 6, 10, 9, 0, tzinfo=ZoneInfo(TZ))
    eid = await _add_entry(
        db_session, "drink",
        {"kind": "coffee", "sub_type": "coffee", "caffeine_mg": 80, "count": 1},
        when,
    )
    out = await compute_entry_markers(db_session, eid, TZ)
    assert out["type"] == "drink"
    assert "caffeine" in _labels(out)


@pytest.mark.asyncio
async def test_non_caffeinated_drink_uses_info_chip(db_session) -> None:  # type: ignore[no-untyped-def]
    when = datetime(2026, 6, 10, 9, 0, tzinfo=ZoneInfo(TZ))
    eid = await _add_entry(
        db_session, "drink",
        {"kind": "water", "sub_type": "water", "caffeine_mg": 0, "count": 1},
        when,
    )
    out = await compute_entry_markers(db_session, eid, TZ)
    assert "drink" in _labels(out)
    assert "caffeine" not in _labels(out)


@pytest.mark.asyncio
async def test_food_marker_emits_macros(db_session) -> None:  # type: ignore[no-untyped-def]
    when = datetime(2026, 6, 10, 13, 0, tzinfo=ZoneInfo(TZ))
    eid = await _add_entry(
        db_session, "food",
        {
            "description": "chicken",
            "meal_type": "lunch",
            "nutrition": {"calories": 250, "protein_g": 30, "carbs_g": 0, "fat_g": 14},
        },
        when,
    )
    out = await compute_entry_markers(db_session, eid, TZ)
    labels = _labels(out)
    assert "calories" in labels
    assert "protein" in labels


@pytest.mark.asyncio
async def test_score_marker_for_mood(db_session) -> None:  # type: ignore[no-untyped-def]
    when = datetime(2026, 6, 10, 18, 0, tzinfo=ZoneInfo(TZ))
    eid = await _add_entry(db_session, "mood", {"score": 4}, when)
    out = await compute_entry_markers(db_session, eid, TZ)
    assert out["type"] == "mood"
    assert "time" in _labels(out)


@pytest.mark.asyncio
async def test_symptom_marker(db_session) -> None:  # type: ignore[no-untyped-def]
    when = datetime(2026, 6, 10, 20, 0, tzinfo=ZoneInfo(TZ))
    eid = await _add_entry(db_session, "symptom", {"tag": "headache", "severity": 4}, when)
    out = await compute_entry_markers(db_session, eid, TZ)
    assert "headache" in _labels(out)
