"""Pydantic schemas for the `routines` table and its endpoints (Phase B).

A routine is a user-configurable scheduled action: either an `ai_review`
(run the agent, DM the reply) or a `reminder` (DM fixed text). The web UI and
the chat agent's routine tools both build/read these shapes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lattice.models import Routine as RoutineRow
from lattice.models.routine import ALL_WEEKDAYS

RoutineType = Literal["ai_review", "reminder"]
Chattiness = Literal["always", "only_notable"]


class RoutineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: RoutineType
    hour: int
    minute: int
    weekday_mask: int
    instruction: str | None
    chattiness: Chattiness
    reminder_text: str | None
    enabled: bool
    last_run_at: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: RoutineRow) -> RoutineOut:
        return cls(
            id=row.id,
            name=row.name,
            type=row.type,
            hour=row.hour,
            minute=row.minute,
            weekday_mask=row.weekday_mask,
            instruction=row.instruction,
            chattiness=row.chattiness,
            reminder_text=row.reminder_text,
            enabled=row.enabled,
            last_run_at=row.last_run_at,
            created_at=row.created_at,
        )


class RoutineListResponse(BaseModel):
    items: list[RoutineOut]
    total: int


class RoutineIn(BaseModel):
    """Create/replace payload. `reminder` needs `reminder_text`; `ai_review`
    needs `instruction`. Validated below so the API and chat tool reject
    incoherent routines the same way."""

    name: str = Field(min_length=1, max_length=128)
    type: RoutineType
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    weekday_mask: int = Field(default=ALL_WEEKDAYS, ge=1, le=ALL_WEEKDAYS)
    instruction: str | None = Field(default=None, max_length=4000)
    chattiness: Chattiness = "always"
    reminder_text: str | None = Field(default=None, max_length=2000)
    enabled: bool = True

    @model_validator(mode="after")
    def _check_type_fields(self) -> RoutineIn:
        if self.type == "reminder":
            if not (self.reminder_text and self.reminder_text.strip()):
                raise ValueError("reminder routines require reminder_text")
        elif self.type == "ai_review":
            if not (self.instruction and self.instruction.strip()):
                raise ValueError("ai_review routines require instruction")
        return self


class RoutinePatch(BaseModel):
    """Partial update — every field optional. Type-coherence is re-checked in
    the endpoint against the merged row."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    type: RoutineType | None = None
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    weekday_mask: int | None = Field(default=None, ge=1, le=ALL_WEEKDAYS)
    instruction: str | None = Field(default=None, max_length=4000)
    chattiness: Chattiness | None = None
    reminder_text: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


__all__ = [
    "Chattiness",
    "RoutineIn",
    "RoutineListResponse",
    "RoutineOut",
    "RoutinePatch",
    "RoutineType",
]
