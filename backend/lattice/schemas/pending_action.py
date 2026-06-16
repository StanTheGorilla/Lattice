"""Pydantic schemas for the `pending_actions` table and its endpoints.

Durable open commitments the chat agent records via its pending-action tools.
The web UI uses these schemas to view, edit, resolve, and delete entries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lattice.models import PendingAction as PendingActionRow

MAX_PENDING_LEN = 300

PendingStatus = Literal["open", "done", "dropped"]


class PendingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    summary: str
    detail: str | None
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: PendingActionRow) -> PendingActionOut:
        return cls(
            id=row.id,
            summary=row.summary,
            detail=row.detail,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class PendingActionListResponse(BaseModel):
    items: list[PendingActionOut]
    total: int


class PendingActionCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=MAX_PENDING_LEN)
    detail: str | None = Field(default=None, max_length=MAX_PENDING_LEN)


class PendingActionPatch(BaseModel):
    summary: str | None = Field(default=None, min_length=1, max_length=MAX_PENDING_LEN)
    detail: str | None = Field(default=None, max_length=MAX_PENDING_LEN)
    status: PendingStatus | None = None
