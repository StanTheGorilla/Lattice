"""Pydantic schemas for the `ai_journal` table and its endpoints.

Self-authored soft guidance the chat agent writes to itself. The web UI uses
these schemas to view, edit, retire, and delete entries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lattice.models import AIJournal as AIJournalRow

MAX_JOURNAL_LEN = 300

JournalKind = Literal["observation", "correction"]


class AIJournalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry: str
    kind: str
    trigger: str | None
    weight: int
    active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: AIJournalRow) -> AIJournalOut:
        return cls(
            id=row.id,
            entry=row.entry,
            kind=row.kind,
            trigger=row.trigger,
            weight=row.weight,
            active=row.active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class AIJournalListResponse(BaseModel):
    items: list[AIJournalOut]
    total: int


class AIJournalCreate(BaseModel):
    entry: str = Field(min_length=1, max_length=MAX_JOURNAL_LEN)
    kind: JournalKind = "observation"
    trigger: str | None = Field(default=None, max_length=MAX_JOURNAL_LEN)


class AIJournalPatch(BaseModel):
    entry: str | None = Field(default=None, min_length=1, max_length=MAX_JOURNAL_LEN)
    kind: JournalKind | None = None
    trigger: str | None = Field(default=None, max_length=MAX_JOURNAL_LEN)
    active: bool | None = None
