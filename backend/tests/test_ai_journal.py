"""Tests for the AI journal tool handlers (Goal 2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from lattice.llm.router import (
    _MAX_JOURNAL_LEN,
    _h_journal_observation,
    _h_reinforce_journal,
    _h_retire_journal,
)
from lattice.models import AIJournal


@pytest.mark.asyncio
async def test_journal_observation_creates_row(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_journal_observation(
        db_session, {"entry": "  user formats lists with - dashes  ", "trigger": "  lists  "}
    )
    assert "id" in out
    assert out["kind"] == "observation"
    assert out["weight"] == 1
    row = await db_session.get(AIJournal, out["id"])
    assert row is not None
    assert row.entry == "user formats lists with - dashes"
    assert row.trigger == "lists"
    assert row.active is True


@pytest.mark.asyncio
async def test_journal_kind_defaults_and_correction(db_session) -> None:  # type: ignore[no-untyped-def]
    obs = await _h_journal_observation(db_session, {"entry": "be terse"})
    assert obs["kind"] == "observation"
    corr = await _h_journal_observation(
        db_session, {"entry": "stop hedging", "kind": "correction"}
    )
    assert corr["kind"] == "correction"
    row = await db_session.get(AIJournal, corr["id"])
    assert row.kind == "correction"


@pytest.mark.asyncio
async def test_duplicate_entry_auto_reinforces(db_session) -> None:  # type: ignore[no-untyped-def]
    first = await _h_journal_observation(db_session, {"entry": "match dash bullets"})
    assert first["weight"] == 1
    second = await _h_journal_observation(db_session, {"entry": "match dash bullets"})
    assert second["id"] == first["id"]
    assert second["weight"] == 2
    rows = list((await db_session.execute(select(AIJournal))).scalars())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_reinforce_journal_bumps_weight(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_journal_observation(db_session, {"entry": "answer directly"})
    out = await _h_reinforce_journal(db_session, {"id": created["id"]})
    assert out["weight"] == 2
    row = await db_session.get(AIJournal, created["id"])
    assert row.weight == 2


@pytest.mark.asyncio
async def test_retire_journal_deactivates(db_session) -> None:  # type: ignore[no-untyped-def]
    created = await _h_journal_observation(db_session, {"entry": "prefers metric units"})
    out = await _h_retire_journal(db_session, {"id": created["id"]})
    assert out["retired"] is True
    row = await db_session.get(AIJournal, created["id"])
    assert row.active is False


@pytest.mark.asyncio
async def test_journal_rejects_empty_entry(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_journal_observation(db_session, {"entry": "   "})
    assert "error" in out


@pytest.mark.asyncio
async def test_journal_enforces_length_cap(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_journal_observation(db_session, {"entry": "x" * (_MAX_JOURNAL_LEN + 1)})
    assert "error" in out


@pytest.mark.asyncio
async def test_journal_rejects_bad_kind(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_journal_observation(db_session, {"entry": "ok", "kind": "nope"})
    assert "error" in out


@pytest.mark.asyncio
async def test_reinforce_missing_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_reinforce_journal(db_session, {"id": 99999})
    assert "error" in out


@pytest.mark.asyncio
async def test_reinforce_requires_int_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_reinforce_journal(db_session, {"id": "abc"})
    assert "error" in out


@pytest.mark.asyncio
async def test_retire_missing_id(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await _h_retire_journal(db_session, {"id": 99999})
    assert "error" in out
