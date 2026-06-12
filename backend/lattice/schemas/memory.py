"""Pydantic schemas for the `user_memory` table and its endpoints.

Persistent agent memory: small durable facts the chat agent records about the
user and recalls across conversations. The web UI uses these schemas to view,
create, edit, and delete entries.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lattice.models import UserMemory as MemoryRow

MAX_MEMORY_LEN = 500


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: MemoryRow) -> MemoryOut:
        return cls(
            id=row.id,
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class MemoryListResponse(BaseModel):
    items: list[MemoryOut]
    total: int


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MEMORY_LEN)


class MemoryPatch(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_MEMORY_LEN)
