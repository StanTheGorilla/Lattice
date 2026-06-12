"""Pydantic schemas for the F1–F5, F8, F9a endpoints (SPEC §5.5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# F1 — readiness
# --------------------------------------------------------------------------- #

ReadinessCategory = Literal["peak", "solid", "average", "low", "depleted"]


class ReadinessExplanation(BaseModel):
    weights_used: dict[str, float]
    missing: list[str] = Field(default_factory=list)
    components: dict[str, float]  # 0-1 normalized component values
    notes: list[str] = Field(default_factory=list)


class ReadinessOutput(BaseModel):
    date: str
    score: int  # 0-100
    category: ReadinessCategory
    provisional: bool = False
    explanation: ReadinessExplanation


# --------------------------------------------------------------------------- #
# F2 — work windows
# --------------------------------------------------------------------------- #


class WorkWindow(BaseModel):
    start: str  # ISO 8601 with TZ offset
    end: str
    duration_minutes: float
    predicted_focus: int  # 0-100
    rationale: list[str]


class WorkWindowsOutput(BaseModel):
    date: str
    min_minutes: int
    windows: list[WorkWindow]
    peak_focus_hour: int | None = None  # local hour 0-23
    confidence_hint: Literal["low", "medium", "high"] = "medium"


# --------------------------------------------------------------------------- #
# F3 — training recommendation
# --------------------------------------------------------------------------- #

TrainingRec = Literal["rest", "easy", "moderate", "hard"]


class TrainingRecOutput(BaseModel):
    date: str
    recommendation: TrainingRec
    confidence: float  # 0.0–1.0
    rationale: list[str]
    inputs: dict[str, float | int | str | None]


# --------------------------------------------------------------------------- #
# F4 — sleep window
# --------------------------------------------------------------------------- #


class SleepWindowOutput(BaseModel):
    date: str
    bedtime: str  # ISO 8601 with TZ offset
    wake_time: str
    target_duration_min: float
    flags: list[str]
    inputs: dict[str, str | bool | int | float | None]


# --------------------------------------------------------------------------- #
# F5 — caffeine cutoff
# --------------------------------------------------------------------------- #


class CaffeineStatusOutput(BaseModel):
    at: str  # ISO 8601 with TZ offset
    bedtime: str
    residual_at_bedtime_mg: float
    safe_for_new_cup: bool
    last_call_minutes: int | None  # minutes until cutoff; None if already over
    # Informative flags (e.g. "daily cap reached: 120 mg of 100 mg"). The F5
    # residual check stays the same; daily-cap is an *advisory* signal so the
    # AI brain can surface it without blocking decisions (P1-5).
    flags: list[str] = []
    inputs: dict[str, float | int | str | None]


# --------------------------------------------------------------------------- #
# F8 — habit adherence
# --------------------------------------------------------------------------- #


class HabitAdherence(BaseModel):
    habit_id: int
    name: str
    target_per_week: int
    current_streak_days: int
    longest_streak_days: int
    week_completion_pct: float  # 0-100, based on last 7 days vs target
    period_completion_pct: float  # 0-100, based on selected window


class HabitAdherenceOutput(BaseModel):
    from_: str = Field(serialization_alias="from")
    to: str
    items: list[HabitAdherence]


# --------------------------------------------------------------------------- #
# F9a — advisor
# --------------------------------------------------------------------------- #

AdvisorIntent = Literal[
    "learn", "train", "rest", "creative", "meeting", "physical_task",
]


class AdvisorOutput(BaseModel):
    intent: AdvisorIntent
    recommendation: str
    confidence: float  # 0.0–1.0
    window: WorkWindow | None = None
    reasons: list[str]
    alternatives: list[WorkWindow] = Field(default_factory=list)


__all__ = [
    "AdvisorIntent",
    "AdvisorOutput",
    "CaffeineStatusOutput",
    "HabitAdherence",
    "HabitAdherenceOutput",
    "ReadinessCategory",
    "ReadinessExplanation",
    "ReadinessOutput",
    "SleepWindowOutput",
    "TrainingRec",
    "TrainingRecOutput",
    "WorkWindow",
    "WorkWindowsOutput",
]
