"""Schema round-trip tests for the 8 entry types (SPEC §4.7)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lattice.schemas.entries import (
    DrinkData,
    EnergyData,
    EntryOut,
    FocusData,
    FoodData,
    MoodData,
    NoteData,
    SymptomData,
    WorkoutManualData,
    validate_data_for_type,
)

# --------------------------------------------------------------------------- #
# Happy paths — one per type
# --------------------------------------------------------------------------- #


def test_food_minimal() -> None:
    m = validate_data_for_type("food", {"description": "pasta"})
    assert isinstance(m, FoodData)
    assert m.meal_type is None


def test_food_with_meal_type() -> None:
    m = validate_data_for_type("food", {"description": "oats", "meal_type": "breakfast"})
    assert isinstance(m, FoodData)
    assert m.meal_type == "breakfast"


def test_drink_coffee() -> None:
    m = validate_data_for_type("drink", {"kind": "coffee", "count": 1})
    assert isinstance(m, DrinkData)
    assert m.kind == "coffee"


def test_mood() -> None:
    m = validate_data_for_type("mood", {"score": 4, "note": "good"})
    assert isinstance(m, MoodData)
    assert m.score == 4


def test_energy() -> None:
    m = validate_data_for_type("energy", {"score": 3})
    assert isinstance(m, EnergyData)


def test_focus() -> None:
    m = validate_data_for_type(
        "focus", {"score": 5, "session_duration_min": 90, "task": "Lattice 2D"},
    )
    assert isinstance(m, FocusData)
    assert m.session_duration_min == 90.0


def test_symptom() -> None:
    m = validate_data_for_type(
        "symptom", {"tag": "headache", "severity": 3, "note": "dull"},
    )
    assert isinstance(m, SymptomData)


def test_note() -> None:
    m = validate_data_for_type("note", {"text": "remember to drink water"})
    assert isinstance(m, NoteData)


def test_workout_manual() -> None:
    m = validate_data_for_type(
        "workout_manual",
        {"kind": "rowing", "duration_min": 30, "intensity": "medium"},
    )
    assert isinstance(m, WorkoutManualData)


# --------------------------------------------------------------------------- #
# Validation failures
# --------------------------------------------------------------------------- #


def test_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown entry type"):
        validate_data_for_type("nonsense", {"foo": "bar"})


def test_mood_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_data_for_type("mood", {"score": 99})


def test_symptom_invalid_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_data_for_type("symptom", {"tag": "spleen", "severity": 2})


def test_drink_free_text_kind_accepted() -> None:
    # kind is now free-text — any string is valid
    result = validate_data_for_type("drink", {"kind": "latte"})
    assert result.kind == "latte"  # type: ignore[attr-defined]
    result2 = validate_data_for_type("drink", {"kind": "kombucha"})
    assert result2.kind == "kombucha"  # type: ignore[attr-defined]


def test_workout_manual_missing_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_data_for_type("workout_manual", {"kind": "row"})


# --------------------------------------------------------------------------- #
# EntryOut.from_row JSON parsing
# --------------------------------------------------------------------------- #


class _FakeRow:
    """Mimics SQLAlchemy ORM row attribute access."""

    def __init__(self, **kw: object) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def test_entry_out_parses_data_json() -> None:
    row = _FakeRow(
        id=1,
        timestamp="2026-05-14T10:00:00+02:00",
        logged_at="2026-05-14T10:00:01+00:00",
        type="food",
        data='{"description": "oats", "meal_type": "breakfast"}',
        source="web",
    )
    out = EntryOut.from_row(row)  # type: ignore[arg-type]
    assert out.data == {"description": "oats", "meal_type": "breakfast"}
    assert out.type == "food"


def test_entry_out_handles_malformed_data() -> None:
    row = _FakeRow(
        id=2,
        timestamp="2026-05-14T10:00:00+02:00",
        logged_at="2026-05-14T10:00:01+00:00",
        type="note",
        data="not even json",
        source="web",
    )
    out = EntryOut.from_row(row)  # type: ignore[arg-type]
    assert out.data == {"_raw": "not even json", "_error": "malformed_json"}
