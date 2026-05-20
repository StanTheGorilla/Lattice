"""Pydantic schemas for `habit_definitions` and `habit_checkins` (SPEC §4.5).

SPEC §5.x does not enumerate habit endpoints; the shapes below mirror the
entries CRUD style and add a nested checkins resource per definition.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HabitDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_per_week: int = Field(default=7, ge=1, le=7)
    active: bool = True


class HabitDefinitionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    target_per_week: int | None = Field(default=None, ge=1, le=7)
    active: bool | None = None


class HabitDefinitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target_per_week: int
    active: bool
    created_at: str


class HabitCheckinCreate(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    completed: bool = True
    note: str | None = None


class HabitCheckinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    habit_id: int
    date: str
    completed: bool
    note: str | None = None


class HabitCheckinListResponse(BaseModel):
    items: list[HabitCheckinOut]


__all__ = [
    "HabitCheckinCreate",
    "HabitCheckinListResponse",
    "HabitCheckinOut",
    "HabitDefinitionCreate",
    "HabitDefinitionOut",
    "HabitDefinitionPatch",
]
