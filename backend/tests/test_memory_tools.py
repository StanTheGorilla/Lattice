"""Tests for the chat agent's memory tool handlers (P2-2)."""

from __future__ import annotations

import pytest

from lattice.llm.router import _h_forget, _h_remember, _h_update_memory
from lattice.models import UserMemory


@pytest.mark.asyncio
async def test_remember_creates_row(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_remember(db_session, {"content": "  prefers teen sleep norms  "})
    assert "id" in out
    assert out["content"] == "prefers teen sleep norms"
    row = await db_session.get(UserMemory, out["id"])
    assert row is not None
    assert row.content == "prefers teen sleep norms"


@pytest.mark.asyncio
async def test_remember_rejects_empty(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_remember(db_session, {"content": "   "})
    assert "error" in out


@pytest.mark.asyncio
async def test_update_memory_changes_content(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_remember(db_session, {"content": "old"})
    out = await _h_update_memory(db_session, {"id": created["id"], "content": "new"})
    assert out["content"] == "new"
    row = await db_session.get(UserMemory, created["id"])
    assert row.content == "new"


@pytest.mark.asyncio
async def test_update_memory_missing_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_update_memory(db_session, {"id": 12345, "content": "x"})
    assert "error" in out


@pytest.mark.asyncio
async def test_update_memory_requires_int_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_update_memory(db_session, {"id": "abc", "content": "x"})
    assert "error" in out


@pytest.mark.asyncio
async def test_forget_deletes_row(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_remember(db_session, {"content": "ephemeral"})
    out = await _h_forget(db_session, {"id": created["id"]})
    assert out["forgot"] == created["id"]
    assert await db_session.get(UserMemory, created["id"]) is None


@pytest.mark.asyncio
async def test_forget_missing(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_forget(db_session, {"id": 99999})
    assert "error" in out
