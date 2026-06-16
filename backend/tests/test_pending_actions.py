"""Tests for the open-commitments (pending_actions) tool handlers (Goal 1b)."""

from __future__ import annotations

import pytest

from lattice.llm.router import (
    _MAX_PENDING_LEN,
    _h_note_pending_action,
    _h_resolve_pending_action,
)
from lattice.models import PendingAction


@pytest.mark.asyncio
async def test_note_creates_open_row(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_note_pending_action(
        db_session, {"summary": "  add gym to calendar  ", "detail": "after time confirmed"}
    )
    assert "id" in out
    assert out["status"] == "open"
    assert out["summary"] == "add gym to calendar"
    row = await db_session.get(PendingAction, out["id"])
    assert row is not None
    assert row.status == "open"
    assert row.detail == "after time confirmed"


@pytest.mark.asyncio
async def test_note_rejects_empty_summary(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_note_pending_action(db_session, {"summary": "   "})
    assert "error" in out


@pytest.mark.asyncio
async def test_note_enforces_length_cap(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_note_pending_action(db_session, {"summary": "x" * (_MAX_PENDING_LEN + 1)})
    assert "error" in out


@pytest.mark.asyncio
async def test_resolve_done(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_note_pending_action(db_session, {"summary": "do thing"})
    out = await _h_resolve_pending_action(db_session, {"id": created["id"], "outcome": "done"})
    assert out["status"] == "done"
    row = await db_session.get(PendingAction, created["id"])
    assert row.status == "done"


@pytest.mark.asyncio
async def test_resolve_dropped(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_note_pending_action(db_session, {"summary": "do thing"})
    out = await _h_resolve_pending_action(db_session, {"id": created["id"], "outcome": "dropped"})
    assert out["status"] == "dropped"
    row = await db_session.get(PendingAction, created["id"])
    assert row.status == "dropped"


@pytest.mark.asyncio
async def test_resolve_missing_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_resolve_pending_action(db_session, {"id": 99999, "outcome": "done"})
    assert "error" in out


@pytest.mark.asyncio
async def test_resolve_requires_int_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_resolve_pending_action(db_session, {"id": "abc", "outcome": "done"})
    assert "error" in out


@pytest.mark.asyncio
async def test_resolve_rejects_bad_outcome(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_note_pending_action(db_session, {"summary": "do thing"})
    out = await _h_resolve_pending_action(db_session, {"id": created["id"], "outcome": "nope"})
    assert "error" in out
