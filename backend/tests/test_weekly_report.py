"""F7 orchestrator (Stage B + persistence) tests.

DeepSeek is mocked. The orchestrator's job is:
- compute Stage A,
- call DeepSeek with the locked prompt,
- UPSERT into weekly_reports keyed on iso_week,
- fall back to a deterministic summary when the LLM is unavailable.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select

from lattice.functions import weekly_report as wr
from lattice.integrations.deepseek import DeepSeekUnavailable
from lattice.models import WeeklyReport

from .conftest import add_metric


async def _seed_a_few_days(db_session) -> date:
    monday = date(2026, 5, 11)
    for i, v in enumerate((70, 75, 80)):
        await add_metric(db_session, "sleep_score", float(v), monday + timedelta(days=i))
    return monday


def _completion(text: str) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


async def _fake_chat_ok(**_: Any) -> Any:
    return _completion("Solid week overall. Best day Wednesday. Top driver: sleep.")


async def _fake_chat_unavailable(**_: Any) -> Any:
    raise DeepSeekUnavailable("simulated outage")


@pytest.mark.asyncio
async def test_generate_persists_with_llm_summary(db_session) -> None:
    monday = await _seed_a_few_days(db_session)
    with patch.object(wr, "chat_completion", new=_fake_chat_ok):
        row = await wr.generate_weekly_report(db_session, target=monday)
    assert row.iso_week == "2026-W20"
    assert row.model_used  # whatever the default is
    assert "Solid week overall" in row.summary_text
    parsed = json.loads(row.stats_json)
    assert parsed["iso_week"] == "2026-W20"
    assert parsed["week_start"] == "2026-05-11"


@pytest.mark.asyncio
async def test_generate_overwrites_existing_row(db_session) -> None:
    """Per 2I decision: POST .../generate is idempotent (overwrites)."""
    monday = await _seed_a_few_days(db_session)
    with patch.object(wr, "chat_completion", new=_fake_chat_ok):
        first = await wr.generate_weekly_report(db_session, target=monday)
    first_id = first.id

    async def second_call(**_: Any) -> Any:
        return _completion("Different summary.")

    with patch.object(wr, "chat_completion", new=second_call):
        second = await wr.generate_weekly_report(db_session, target=monday)

    rows = (await db_session.execute(select(WeeklyReport))).scalars().all()
    assert len(rows) == 1
    assert second.id == first_id
    assert second.summary_text == "Different summary."


@pytest.mark.asyncio
async def test_generate_falls_back_when_llm_unavailable(db_session) -> None:
    monday = await _seed_a_few_days(db_session)
    with patch.object(wr, "chat_completion", new=_fake_chat_unavailable):
        row = await wr.generate_weekly_report(db_session, target=monday)
    assert row.model_used == "deterministic-only"
    # Deterministic fallback always references the week label.
    assert "2026-W20" in row.summary_text


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent(db_session) -> None:
    monday = date(2026, 5, 11)
    prior_monday = monday - timedelta(days=7)
    with patch.object(wr, "chat_completion", new=_fake_chat_ok):
        await wr.generate_weekly_report(db_session, target=prior_monday)
        latest = await wr.generate_weekly_report(db_session, target=monday)
    fetched = await wr.get_latest_weekly_report(db_session)
    assert fetched is not None
    assert fetched.iso_week == latest.iso_week
