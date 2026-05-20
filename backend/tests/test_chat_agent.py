"""Chat agent loop tests.

DeepSeek is mocked end-to-end so these tests run offline. The mock honors
the same `chat.completions.create(...)` shape that the openai SDK returns,
producing a scripted sequence of tool_calls then a final reply.

Coverage:
- Read tool path: `get_readiness` resolves and the agent replies with content.
- Write tool path: `log_entry` actually creates a DB row and is reported in
  `actions_taken`.
- Iteration cap: agent stops gracefully when the model keeps calling tools.
- Tool dispatch error path: unknown tool name surfaces as a tool error to
  the model without crashing the loop.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select

from lattice.llm import router as llm_router
from lattice.models import Entry

from .conftest import add_metric


def _msg(*, content: str = "", tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def _tc(name: str, args: dict[str, Any], tc_id: str = "call_1") -> Any:
    return SimpleNamespace(
        id=tc_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _completion(message: Any) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _Script:
    """A deterministic stand-in for the openai chat.completions.create call."""

    def __init__(self, completions: list[Any]) -> None:
        self.completions = list(completions)
        self.calls = 0

    async def __call__(self, **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls += 1
        if not self.completions:
            return _completion(_msg(content="(script exhausted)"))
        return self.completions.pop(0)


@pytest.mark.asyncio
async def test_read_path_returns_reply(db_session: Any) -> None:
    today = date.today()
    # Seed enough metrics so compute_readiness can produce a real score.
    await add_metric(db_session, "hrv_overnight_avg", 60.0, today)
    await add_metric(db_session, "sleep_score", 80.0, today)
    await add_metric(db_session, "resting_hr", 55.0, today)
    await add_metric(db_session, "body_battery_start", 90.0, today)
    await add_metric(db_session, "stress_avg", 25.0, today)

    script = _Script([
        _completion(_msg(tool_calls=[_tc("get_readiness", {})])),
        _completion(_msg(content="Readiness today is solid.")),
    ])
    with patch.object(llm_router, "chat_completion", new=script):
        result = await llm_router.run_agent(
            db_session, history=[], user_message="How is my readiness?",
        )

    assert script.calls == 2
    assert result.reply == "Readiness today is solid."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_readiness"
    assert result.tool_calls[0].ok is True
    assert result.actions_taken == []


@pytest.mark.asyncio
async def test_write_path_persists_entry_and_reports_action(db_session: Any) -> None:
    script = _Script([
        _completion(_msg(tool_calls=[
            _tc("log_entry", {"type": "drink", "data": {"kind": "coffee", "count": 1}}),
        ])),
        _completion(_msg(content="Logged 1 coffee.")),
    ])
    with patch.object(llm_router, "chat_completion", new=script):
        result = await llm_router.run_agent(
            db_session, history=[], user_message="log a coffee",
        )

    assert result.reply == "Logged 1 coffee."
    assert result.actions_taken == ["log_entry"]

    rows = (await db_session.execute(select(Entry))).scalars().all()
    assert len(rows) == 1
    assert rows[0].type == "drink"
    assert rows[0].source == "discord"


@pytest.mark.asyncio
async def test_iteration_cap_breaks_runaway_loops(db_session: Any) -> None:
    # Always returns a tool call → would loop forever without a cap.
    looping = _Script([
        _completion(_msg(tool_calls=[_tc("get_readiness", {})]))
        for _ in range(50)
    ])
    with patch.object(llm_router, "chat_completion", new=looping):
        result = await llm_router.run_agent(
            db_session,
            history=[],
            user_message="loop forever",
            max_iters=3,
        )

    assert result.finish_reason == "iter_cap"
    assert "iteration cap" in result.reply
    assert len(result.tool_calls) == 3


@pytest.mark.asyncio
async def test_unknown_tool_name_surfaces_as_error(db_session: Any) -> None:
    script = _Script([
        _completion(_msg(tool_calls=[_tc("nope", {})])),
        _completion(_msg(content="couldn't find that tool")),
    ])
    with patch.object(llm_router, "chat_completion", new=script):
        result = await llm_router.run_agent(
            db_session, history=[], user_message="hi",
        )

    assert result.tool_calls[0].ok is False
    assert "unknown tool" in result.tool_calls[0].result["error"]
    assert result.reply == "couldn't find that tool"
