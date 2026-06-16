"""Light tests for prompt planning-context blocks (pending + journal)."""

from __future__ import annotations

import pytest

from lattice.llm.prompts import (
    _format_journal,
    _format_pending_actions,
    build_planning_context,
    build_system_prompt,
)


@pytest.mark.asyncio
async def test_planning_context_has_pending_and_journal(db_session) -> None:  # type: ignore[no-untyped-def]
    ctx = await build_planning_context(db_session)
    assert "pending_block" in ctx
    assert "journal_block" in ctx


def test_empty_formatters_return_placeholders() -> None:
    assert _format_pending_actions([]) == "  (no open commitments)"
    assert _format_journal([]) == "  (nothing learned yet)"


def test_system_prompt_renders_without_context() -> None:
    # Guards against a missing .format key (e.g. a new {placeholder} with no arg).
    prompt = build_system_prompt(planning_context=None)
    assert "AI JOURNAL" in prompt
    assert "OPEN COMMITMENTS" in prompt
