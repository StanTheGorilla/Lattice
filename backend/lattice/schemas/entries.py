"""Pydantic schemas for the `entries` table and its endpoints (SPEC §4.1, §4.7, §5.2).

One discriminated union models the eight entry types. Each variant validates the
`data` JSON column against the schema in SPEC §4.7, so malformed payloads are
rejected at the API boundary rather than at scoring time.

The on-disk format stores `data` as a JSON string. `EntryOut.from_row` parses
it back into the per-type model so clients receive structured objects.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lattice.models import Entry as EntryRow

# ---------------------------------------------------------------------------
# Drink classification table + helper
# ---------------------------------------------------------------------------

# Ordered list of (pattern, canonical_kind, sub_type, caffeine_mg_per_unit).
# More-specific patterns come before generic ones so substring matching is greedy.
_DRINK_MAP: list[tuple[str, str, str | None, float]] = [
    # espresso-based
    ("ristretto", "coffee", "ristretto", 32.0),
    ("doppio", "coffee", "espresso", 128.0),
    ("double espresso", "coffee", "espresso", 128.0),
    ("espresso", "coffee", "espresso", 64.0),
    ("lungo", "coffee", "lungo", 90.0),
    # milk-based
    ("flat white", "coffee", "flat_white", 130.0),
    ("cappuccino", "coffee", "cappuccino", 120.0),
    ("macchiato", "coffee", "macchiato", 64.0),
    ("cortado", "coffee", "cortado", 64.0),
    ("latte", "coffee", "latte", 150.0),
    # black
    ("long black", "coffee", "americano", 100.0),
    ("americano", "coffee", "americano", 100.0),
    ("moka", "coffee", "moka", 90.0),
    ("turkish", "coffee", "turkish", 60.0),
    ("aeropress", "coffee", "filter", 80.0),
    ("chemex", "coffee", "filter", 95.0),
    ("pour over", "coffee", "filter", 95.0),
    ("french press", "coffee", "filter", 95.0),
    ("drip", "coffee", "filter", 95.0),
    ("filter", "coffee", "filter", 95.0),
    # cold
    ("nitro", "coffee", "cold_brew", 200.0),
    ("cold-brew", "coffee", "cold_brew", 200.0),
    ("cold brew", "coffee", "cold_brew", 200.0),
    # generic — must come after all specific variants
    ("coffee", "coffee", None, 80.0),
    # tea
    ("matcha", "tea", "matcha", 60.0),
    ("green tea", "tea", "green_tea", 30.0),
    ("black tea", "tea", "black_tea", 50.0),
    ("white tea", "tea", "white_tea", 25.0),
    ("oolong", "tea", "oolong", 40.0),
    ("chai", "tea", "chai", 50.0),
    ("tea", "tea", None, 40.0),
    # caffeinated other
    ("pre-workout", "other", "pre_workout", 200.0),
    ("monster", "other", "energy_drink", 160.0),
    ("red bull", "other", "energy_drink", 80.0),
    ("energy drink", "other", "energy_drink", 80.0),
    ("pepsi", "other", "cola", 38.0),
    ("coke", "other", "cola", 34.0),
    ("cola", "other", "cola", 34.0),
    # zero-caffeine
    ("sparkling", "water", "sparkling", 0.0),
    ("water", "water", None, 0.0),
    ("juice", "other", "juice", 0.0),
    ("milk", "other", "milk", 0.0),
    ("soda", "other", "soda", 0.0),
    ("cocktail", "alcohol", "cocktail", 0.0),
    ("whisky", "alcohol", "spirits", 0.0),
    ("whiskey", "alcohol", "spirits", 0.0),
    ("vodka", "alcohol", "spirits", 0.0),
    ("rum", "alcohol", "spirits", 0.0),
    ("gin", "alcohol", "spirits", 0.0),
    ("wine", "alcohol", "wine", 0.0),
    ("beer", "alcohol", "beer", 0.0),
]


def classify_drink(raw: str) -> tuple[str, str | None, float | None]:
    """Return (canonical_kind, sub_type, caffeine_mg_per_unit).

    caffeine_mg is None for non-caffeinated drinks. The caller is responsible
    for multiplying by `count` to get the total dose.
    """
    normalized = raw.strip().lower()
    for pattern, kind, sub_type, caffeine in _DRINK_MAP:
        if pattern in normalized:
            return kind, sub_type, caffeine if caffeine > 0 else None
    return normalized, None, None

# --------------------------------------------------------------------------- #
# Per-type data payloads (SPEC §4.7)
# --------------------------------------------------------------------------- #


class FoodNutrition(BaseModel):
    """Nutritional estimate attached to a food entry (server-generated)."""

    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    fiber_g: float | None = None
    sugar_g: float | None = None
    estimated_grams: float | None = None
    confidence: str | None = None  # high / medium / low
    notes: str | None = None


class FoodData(BaseModel):
    type: Literal["food"] = "food"
    description: str
    grams: float | None = None  # portion weight in grams
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    nutrition: FoodNutrition | None = None  # populated by server after estimation


class DrinkData(BaseModel):
    type: Literal["drink"] = "drink"
    # `kind` is free-text — whatever the user typed (lowercased / trimmed).
    # The `_DRINK_MAP` classifier is now only consulted to derive `sub_type`
    # and `caffeine_mg`; the user's chosen label is preserved verbatim so the
    # AI brain can reason over "latte" / "kombucha" / etc. rather than a
    # bucketed canonical category. Downstream code that needs caffeinated-vs-not
    # should consult `caffeine_mg > 0`, not match on `kind` strings (P1-3).
    kind: str
    sub_type: str | None = None  # specific variant: latte / espresso / etc.
    caffeine_mg: float | None = None  # mg per unit (count=1); None = non-caffeinated
    volume_ml: float | None = None
    count: float | None = None

    @model_validator(mode="after")
    def _auto_classify(self) -> "DrinkData":
        """Lowercase `kind`; fill `sub_type`/`caffeine_mg` from the classifier when absent."""
        if self.kind:
            self.kind = self.kind.strip().lower()
            _, sub_type, caffeine = classify_drink(self.kind)
            if sub_type is not None and self.sub_type is None:
                self.sub_type = sub_type
            if caffeine is not None and self.caffeine_mg is None:
                self.caffeine_mg = caffeine
        return self


class MoodData(BaseModel):
    type: Literal["mood"] = "mood"
    score: int = Field(ge=1, le=5)
    note: str | None = None


class EnergyData(BaseModel):
    type: Literal["energy"] = "energy"
    score: int = Field(ge=1, le=5)
    note: str | None = None


class FocusData(BaseModel):
    type: Literal["focus"] = "focus"
    score: int = Field(ge=1, le=5)
    session_duration_min: float | None = None
    task: str | None = None


class SymptomData(BaseModel):
    type: Literal["symptom"] = "symptom"
    tag: Literal["headache", "fatigue", "gut", "other"]
    severity: int = Field(ge=1, le=5)
    note: str | None = None


class NoteData(BaseModel):
    type: Literal["note"] = "note"
    text: str


class WorkoutManualData(BaseModel):
    type: Literal["workout_manual"] = "workout_manual"
    kind: str
    duration_min: float
    intensity: Literal["low", "medium", "high"]
    note: str | None = None


EntryData = Annotated[
    FoodData | DrinkData | MoodData | EnergyData | FocusData | SymptomData | NoteData | WorkoutManualData,
    Field(discriminator="type"),
]

EntryType = Literal[
    "food", "drink", "mood", "energy", "focus", "symptom", "note", "workout_manual",
]

# Map type → model so the API layer can validate just the `data` dict
# given the parent `type` field.
_TYPE_TO_MODEL: dict[str, type[BaseModel]] = {
    "food": FoodData,
    "drink": DrinkData,
    "mood": MoodData,
    "energy": EnergyData,
    "focus": FocusData,
    "symptom": SymptomData,
    "note": NoteData,
    "workout_manual": WorkoutManualData,
}


def validate_data_for_type(entry_type: str, data: dict[str, Any]) -> BaseModel:
    """Validate `data` against the schema for `entry_type`.

    Injects the discriminator into `data` if absent so callers don't have to
    repeat `type` inside the body.
    """
    model = _TYPE_TO_MODEL.get(entry_type)
    if model is None:
        raise ValueError(f"unknown entry type: {entry_type!r}")
    enriched = {**data, "type": entry_type}
    return model.model_validate(enriched)


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #


class EntryCreate(BaseModel):
    type: EntryType
    data: dict[str, Any]
    timestamp: str | None = None
    source: Literal["discord", "web"] = "web"


class EntryPatch(BaseModel):
    """All fields optional. If `data` is provided, it must round-trip the
    type's schema (the type itself cannot be changed mid-record)."""

    data: dict[str, Any] | None = None
    timestamp: str | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: str
    logged_at: str
    type: EntryType
    data: dict[str, Any]
    source: str

    @classmethod
    def from_row(cls, row: EntryRow) -> EntryOut:
        try:
            parsed = json.loads(row.data)
        except json.JSONDecodeError:
            parsed = {"_raw": row.data, "_error": "malformed_json"}
        return cls(
            id=row.id,
            timestamp=row.timestamp,
            logged_at=row.logged_at,
            type=row.type,  # type: ignore[arg-type]
            data=parsed,
            source=row.source,
        )


class EntryListResponse(BaseModel):
    items: list[EntryOut]
    total: int


__all__ = [
    "DrinkData",
    "EnergyData",
    "EntryCreate",
    "EntryData",
    "EntryListResponse",
    "EntryOut",
    "EntryPatch",
    "EntryType",
    "FocusData",
    "FoodData",
    "FoodNutrition",
    "MoodData",
    "NoteData",
    "SymptomData",
    "ValidationError",
    "WorkoutManualData",
    "classify_drink",
    "validate_data_for_type",
]
