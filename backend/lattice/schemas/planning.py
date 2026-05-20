"""Pydantic schemas for the planning system — SPEC §4.11."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #

SexAtBirth = Literal["male", "female", "intersex", "prefer_not_to_say"]
Chronotype = Literal["morning", "neutral", "evening"]


class ProfilePatch(BaseModel):
    """All fields optional — PATCH semantics (only present fields are updated).

    A field set to JSON `null` clears that field; a field omitted from the
    payload is left untouched.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=128)
    birthday: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex_at_birth: SexAtBirth | None = None
    height_cm: float | None = Field(default=None, ge=50, le=260)
    weight_kg: float | None = Field(default=None, ge=20, le=400)
    chronotype: Chronotype | None = None
    work_pattern: str | None = Field(default=None, max_length=2000)
    health_flags: str | None = Field(default=None, max_length=4000)
    target_sleep_min: int | None = Field(default=None, ge=180, le=720)
    target_wake_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    caffeine_cutoff_hour: int | None = Field(default=None, ge=0, le=23)
    last_meal_cutoff_hour: int | None = Field(default=None, ge=0, le=23)
    screen_off_hour: int | None = Field(default=None, ge=0, le=23)
    calorie_goal: float | None = Field(default=None, ge=500, le=10000)
    protein_g_goal: float | None = Field(default=None, ge=10, le=1000)
    carbs_g_goal: float | None = Field(default=None, ge=10, le=2000)
    fat_g_goal: float | None = Field(default=None, ge=5, le=1000)
    fiber_g_goal: float | None = Field(default=None, ge=1, le=200)
    sugar_g_goal: float | None = Field(default=None, ge=0, le=500)


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str | None
    birthday: str | None
    sex_at_birth: str | None
    height_cm: float | None
    weight_kg: float | None
    chronotype: str | None
    work_pattern: str | None
    health_flags: str | None
    target_sleep_min: int | None
    target_wake_time: str | None
    caffeine_cutoff_hour: int | None
    last_meal_cutoff_hour: int | None
    screen_off_hour: int | None
    calorie_goal: float | None
    protein_g_goal: float | None
    carbs_g_goal: float | None
    fat_g_goal: float | None
    fiber_g_goal: float | None
    sugar_g_goal: float | None
    updated_at: str | None
    age: int | None = None  # derived from birthday


# --------------------------------------------------------------------------- #
# Areas
# --------------------------------------------------------------------------- #


class AreaCreate(BaseModel):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = 0


class AreaPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int | None = None
    archived: bool | None = None


class AreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    description: str | None
    color: str | None
    sort_order: int
    archived: bool
    created_at: str


# --------------------------------------------------------------------------- #
# Initiatives
# --------------------------------------------------------------------------- #

InitiativeStatus = Literal["active", "paused", "completed", "abandoned"]


class InitiativeCreate(BaseModel):
    area_id: int
    title: str = Field(min_length=1, max_length=200)
    why: str | None = Field(default=None, max_length=4000)
    target_outcome: str | None = Field(default=None, max_length=2000)
    target_metric: str | None = Field(default=None, max_length=64)
    target_value: float | None = None
    target_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    review_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class InitiativePatch(BaseModel):
    area_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    why: str | None = Field(default=None, max_length=4000)
    target_outcome: str | None = Field(default=None, max_length=2000)
    target_metric: str | None = Field(default=None, max_length=64)
    target_value: float | None = None
    target_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    review_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: InitiativeStatus | None = None
    outcome_note: str | None = Field(default=None, max_length=4000)


class InitiativeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    area_id: int
    title: str
    why: str | None
    target_outcome: str | None
    target_metric: str | None
    target_value: float | None
    target_date: str | None
    status: str
    review_at: str | None
    created_at: str
    closed_at: str | None
    outcome_note: str | None


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #

DecisionStatus = Literal["open", "decided", "reviewed", "abandoned"]


class DecisionCreate(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    area_id: int | None = None
    initiative_id: int | None = None
    options: list[str] | None = None  # serialized to JSON in DB
    criteria: str | None = Field(default=None, max_length=4000)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class DecisionPatch(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    area_id: int | None = None
    initiative_id: int | None = None
    options: list[str] | None = None
    criteria: str | None = Field(default=None, max_length=4000)
    deadline: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    decision: str | None = Field(default=None, max_length=4000)
    reasoning: str | None = Field(default=None, max_length=8000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    review_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

    outcome: str | None = Field(default=None, max_length=8000)
    outcome_rating: int | None = Field(default=None, ge=1, le=5)

    status: DecisionStatus | None = None


class DecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    area_id: int | None
    initiative_id: int | None
    options: list[str] | None
    criteria: str | None
    deadline: str | None
    decided_at: str | None
    decision: str | None
    reasoning: str | None
    confidence: int | None
    review_at: str | None
    reviewed_at: str | None
    outcome: str | None
    outcome_rating: int | None
    status: str
    created_at: str


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

PlanStatus = Literal["active", "completed", "abandoned"]


class PlanCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    plan: str = Field(min_length=1)
    metric: str | None = Field(default=None, max_length=64)
    target_value: float | None = None
    target_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PlanPatch(BaseModel):
    status: PlanStatus | None = None
    progress_note: str | None = Field(default=None, max_length=4000)
    plan: str | None = None


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    goal: str
    plan: str
    metric: str | None
    target_value: float | None
    target_date: str | None
    status: str
    progress_note: str | None
    created_at: str
    closed_at: str | None


# --------------------------------------------------------------------------- #
# AI rules
# --------------------------------------------------------------------------- #

RuleScope = Literal["global", "area", "initiative"]


class AIRuleCreate(BaseModel):
    rule: str = Field(min_length=1, max_length=2000)
    scope: RuleScope = "global"
    scope_id: int | None = None
    active: bool = True


class AIRulePatch(BaseModel):
    rule: str | None = Field(default=None, min_length=1, max_length=2000)
    scope: RuleScope | None = None
    scope_id: int | None = None
    active: bool | None = None


class AIRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule: str
    scope: str
    scope_id: int | None
    active: bool
    created_at: str


__all__ = [
    "AIRuleCreate",
    "AIRuleOut",
    "AIRulePatch",
    "AreaCreate",
    "AreaOut",
    "AreaPatch",
    "DecisionCreate",
    "DecisionOut",
    "DecisionPatch",
    "InitiativeCreate",
    "InitiativeOut",
    "InitiativePatch",
    "PlanCreate",
    "PlanOut",
    "PlanPatch",
    "ProfileOut",
    "ProfilePatch",
]
