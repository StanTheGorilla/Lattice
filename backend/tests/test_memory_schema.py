"""Schema round-trip + validation tests for persistent agent memory."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lattice.schemas.memory import (
    MAX_MEMORY_LEN,
    MemoryCreate,
    MemoryListResponse,
    MemoryOut,
    MemoryPatch,
)


def test_memory_out_round_trip() -> None:
    out = MemoryOut(
        id=1,
        content="prefers morning workouts",
        created_at="2026-05-21T08:00:00+00:00",
        updated_at="2026-05-21T08:00:00+00:00",
    )
    again = MemoryOut.model_validate(out.model_dump())
    assert again == out


def test_memory_list_response() -> None:
    item = MemoryOut(
        id=2,
        content="training for a marathon in October",
        created_at="2026-05-21T08:00:00+00:00",
        updated_at="2026-05-21T08:00:00+00:00",
    )
    resp = MemoryListResponse(items=[item], total=1)
    assert MemoryListResponse.model_validate(resp.model_dump()) == resp


def test_memory_create_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        MemoryCreate(content="")


def test_memory_create_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        MemoryCreate(content="x" * (MAX_MEMORY_LEN + 1))


def test_memory_patch_accepts_max_length() -> None:
    MemoryPatch(content="y" * MAX_MEMORY_LEN)
