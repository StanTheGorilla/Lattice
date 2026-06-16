"""Tests for the two-tier chat-history floor in _load_history (Goal 1a)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lattice.api.chat import _load_history
from lattice.config import settings
from lattice.models import Conversation

SESSION = "sess-1"


async def _seed(db_session, *, age_minutes: float, n: int = 12) -> None:  # type: ignore[no-untyped-def]
    """Write n alternating user/assistant rows, the newest aged `age_minutes`."""
    base = datetime.now(UTC) - timedelta(minutes=age_minutes)
    for i in range(n):
        # Spread rows a second apart so the newest equals `base`.
        ts = (base - timedelta(seconds=(n - 1 - i))).isoformat(timespec="seconds")
        role = "user" if i % 2 == 0 else "assistant"
        db_session.add(
            Conversation(
                timestamp=ts,
                role=role,
                content=f"msg-{i}",
                tool_calls=None,
                session_id=SESSION,
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_fresh_session_returns_full_window(db_session) -> None:  # type: ignore[no-untyped-def]
    await _seed(db_session, age_minutes=1, n=12)
    history = await _load_history(db_session, SESSION)
    assert len(history) == 12
    assert "[resumed after" not in str(history[0]["content"])


@pytest.mark.asyncio
async def test_stale_session_returns_full_window_with_marker(db_session) -> None:  # type: ignore[no-untyped-def]
    stale_min = settings.chat_session_idle_minutes + 180  # 3h past idle
    await _seed(db_session, age_minutes=stale_min, n=12)
    history = await _load_history(db_session, SESSION)
    # Full window preserved across the gap (no trimming), just marked resumed.
    assert len(history) == 12
    assert str(history[0]["content"]).startswith("[resumed after")
    assert "gap]" in str(history[0]["content"])


@pytest.mark.asyncio
async def test_stale_marker_uses_hours(db_session) -> None:  # type: ignore[no-untyped-def]
    await _seed(db_session, age_minutes=180, n=12)  # ~3h
    history = await _load_history(db_session, SESSION)
    assert "[resumed after 3h gap]" in str(history[0]["content"])
