"""Schema validation tests for routine payloads (Phase B)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lattice.schemas.routine import RoutineIn, RoutineOut


def test_reminder_requires_text() -> None:
    with pytest.raises(ValidationError):
        RoutineIn(name="r", type="reminder", hour=9, minute=0)
    ok = RoutineIn(name="r", type="reminder", hour=9, minute=0, reminder_text="hi")
    assert ok.reminder_text == "hi"


def test_ai_review_requires_instruction() -> None:
    with pytest.raises(ValidationError):
        RoutineIn(name="r", type="ai_review", hour=7, minute=30)
    ok = RoutineIn(
        name="r", type="ai_review", hour=7, minute=30, instruction="review sleep",
    )
    assert ok.instruction == "review sleep"
    assert ok.chattiness == "always"  # default


def test_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutineIn(name="r", type="reminder", hour=24, minute=0, reminder_text="x")
    with pytest.raises(ValidationError):
        RoutineIn(name="r", type="reminder", hour=9, minute=60, reminder_text="x")
    with pytest.raises(ValidationError):
        RoutineIn(name="r", type="reminder", hour=9, minute=0, reminder_text="x",
                  weekday_mask=128)


def test_routine_out_round_trip() -> None:
    payload = {
        "id": 1,
        "name": "Morning brief",
        "type": "ai_review",
        "hour": 7,
        "minute": 30,
        "weekday_mask": 127,
        "instruction": "review",
        "chattiness": "always",
        "reminder_text": None,
        "enabled": True,
        "last_run_at": None,
        "created_at": "2026-06-03T00:00:00+00:00",
    }
    out = RoutineOut(**payload)
    assert out.model_dump() == payload
