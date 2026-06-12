"""Tests for the P2-3 compact tool-result digest.

`build_data_digest` produces a short plain-text summary persisted on the
assistant row; `_load_history` replays it prefixed to the assistant content so
follow-up turns retain the data context without violating the OpenAI tool
message contract.
"""

from __future__ import annotations

import pytest

from lattice.api.chat import _load_history, _persist_turn, build_data_digest
from lattice.schemas.chat import ToolCallSummary


def _summary(name: str, result: dict, ok: bool = True) -> ToolCallSummary:
    return ToolCallSummary(name=name, arguments={}, result=result, ok=ok)


def test_digest_none_when_no_tools() -> None:
    assert build_data_digest([]) is None


def test_digest_none_when_all_failed() -> None:
    assert build_data_digest([_summary("get_readiness", {}, ok=False)]) is None


def test_digest_picks_salient_keys() -> None:
    digest = build_data_digest([
        _summary("get_readiness", {"score": 77, "category": "solid", "extra": "x"}),
    ])
    assert digest is not None
    assert digest.startswith("data consulted:")
    assert "score=77" in digest
    assert "category=solid" in digest


def test_digest_truncated() -> None:
    big = {f"k{i}": "v" * 50 for i in range(20)}
    digest = build_data_digest([_summary("t", big)])
    assert digest is not None
    assert len(digest) <= 400


@pytest.mark.asyncio
async def test_digest_persisted_and_replayed(db_session) -> None:  # type: ignore[no-untyped-def]
    summaries = [_summary("get_readiness", {"score": 77, "category": "solid"})]
    await _persist_turn(
        db_session,
        session_id="s1",
        user_message="how am I?",
        assistant_reply="You're solid today.",
        tool_summaries=summaries,
    )

    history = await _load_history(db_session, "s1")
    assistant_msgs = [m for m in history if m["role"] == "assistant"]
    assert assistant_msgs
    content = assistant_msgs[0]["content"]
    assert "data consulted" in content
    assert "score=77" in content
    assert "You're solid today." in content
