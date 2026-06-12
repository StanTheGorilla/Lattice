"""Tests for functions/llm_observability.py (P3-1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from lattice.functions.llm_observability import get_llm_usage_summary
from lattice.models import LLMUsage

TZ = "Europe/Warsaw"


async def _add_usage(session, day: str, in_tok: int, out_tok: int) -> None:
    session.add(LLMUsage(date=day, input_tokens=in_tok, output_tokens=out_tok))
    await session.commit()


@pytest.mark.asyncio
async def test_empty_usage(db_session) -> None:  # type: ignore[no-untyped-def]
    out = await get_llm_usage_summary(db_session)
    assert out["days"] == []
    assert out["totals"]["total_tokens"] == 0
    assert out["totals"]["est_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_aggregates_and_costs(db_session) -> None:  # type: ignore[no-untyped-def]
    today = datetime.now(ZoneInfo(TZ)).date()
    await _add_usage(db_session, today.isoformat(), 1_000_000, 1_000_000)
    await _add_usage(db_session, (today - timedelta(days=1)).isoformat(), 500_000, 0)

    out = await get_llm_usage_summary(db_session, days=7)
    assert len(out["days"]) == 2
    # newest first
    assert out["days"][0]["date"] == today.isoformat()
    assert out["totals"]["input_tokens"] == 1_500_000
    assert out["totals"]["output_tokens"] == 1_000_000
    # cost = 1.5 * input_rate + 1.0 * output_rate
    expected = round(1.5 * out["input_usd_per_mtok"] + 1.0 * out["output_usd_per_mtok"], 4)
    assert out["totals"]["est_cost_usd"] == expected


@pytest.mark.asyncio
async def test_window_excludes_old_rows(db_session) -> None:  # type: ignore[no-untyped-def]
    today = datetime.now(ZoneInfo(TZ)).date()
    await _add_usage(db_session, today.isoformat(), 100, 100)
    await _add_usage(db_session, (today - timedelta(days=40)).isoformat(), 999, 999)

    out = await get_llm_usage_summary(db_session, days=7)
    assert len(out["days"]) == 1
    assert out["totals"]["input_tokens"] == 100
