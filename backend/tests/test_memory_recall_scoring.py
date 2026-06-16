"""Tests for relevance-ranked memory recall (_score_memories, Goal 1d)."""

from __future__ import annotations

from lattice.llm.prompts import _score_memories
from lattice.models import UserMemory


def _mem(mem_id: int, content: str, created_at: str) -> UserMemory:
    return UserMemory(id=mem_id, content=content, created_at=created_at, updated_at=created_at)


def test_overlapping_memory_outranks_newer_unrelated() -> None:
    older_relevant = _mem(1, "trains for a marathon and tracks running pace", "2026-01-01T00:00:00")
    newer_unrelated = _mem(2, "prefers oat milk in coffee", "2026-06-01T00:00:00")
    ranked = _score_memories([newer_unrelated, older_relevant], "how is my marathon running going")
    assert ranked[0].id == 1  # topical overlap wins despite being older


def test_none_message_preserves_recency_order() -> None:
    # Caller passes recency-sorted rows; with no message order is unchanged.
    rows = [
        _mem(2, "newer fact", "2026-06-01T00:00:00"),
        _mem(1, "older fact", "2026-01-01T00:00:00"),
    ]
    ranked = _score_memories(rows, None)
    assert [m.id for m in ranked] == [2, 1]


def test_tie_breaks_on_recency() -> None:
    # Neither overlaps the message → all score 0 → recency tiebreak (desc).
    rows = [
        _mem(1, "older fact", "2026-01-01T00:00:00"),
        _mem(2, "newer fact", "2026-06-01T00:00:00"),
    ]
    ranked = _score_memories(rows, "completely different topic xyz")
    assert ranked[0].id == 2
