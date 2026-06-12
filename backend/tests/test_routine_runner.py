"""Routine runner unit tests (Phase B).

Covers the two behaviours that must not drift: the `only_notable` sentinel
suppression and the plain `reminder` DM path. `send_dm` and `run_agent` are
monkeypatched so no network or LLM call happens.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lattice.functions import routine_runner
from lattice.functions.routine_runner import (
    NOTABLE_SENTINEL,
    build_ai_review_prompt,
    run_routine,
)
from lattice.models import Routine
from lattice.sync.scheduler import _weekday_mask_to_cron


def _routine(**kw: object) -> Routine:
    base: dict[str, object] = {
        "name": "t",
        "type": "reminder",
        "hour": 9,
        "minute": 0,
        "weekday_mask": 127,
        "instruction": None,
        "chattiness": "always",
        "reminder_text": "stretch",
        "enabled": True,
        "last_run_at": None,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    base.update(kw)
    return Routine(**base)  # type: ignore[arg-type]


def test_weekday_mask_to_cron() -> None:
    assert _weekday_mask_to_cron(127) == "*"
    assert _weekday_mask_to_cron(0b0011111) == "0,1,2,3,4"  # Mon–Fri
    assert _weekday_mask_to_cron(0b1100000) == "5,6"  # weekend
    assert _weekday_mask_to_cron(0b0000001) == "0"  # Monday only


def test_notability_contract_embeds_sentinel() -> None:
    prompt = build_ai_review_prompt("review recovery", only_notable=True)
    assert NOTABLE_SENTINEL in prompt
    # `always` routines get the bare instruction, no contract.
    assert build_ai_review_prompt("review recovery", only_notable=False) == "review recovery"


@pytest.mark.asyncio
async def test_reminder_sends_text(db_session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sent: list[str] = []

    async def fake_send(content: str) -> bool:
        sent.append(content)
        return True

    monkeypatch.setattr(routine_runner, "send_dm", fake_send)
    row = _routine(type="reminder", reminder_text="drink water")
    db_session.add(row)
    await db_session.commit()

    result = await run_routine(db_session, row)

    assert sent == ["drink water"]
    assert result.sent is True
    assert result.suppressed is False
    assert row.last_run_at is not None


@pytest.mark.asyncio
async def test_only_notable_suppresses_on_sentinel(db_session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sent: list[str] = []

    async def fake_send(content: str) -> bool:
        sent.append(content)
        return True

    class _Result:
        reply = f"  {NOTABLE_SENTINEL}.  "

    async def fake_agent(session, *, history, user_message):  # type: ignore[no-untyped-def]
        return _Result()

    monkeypatch.setattr(routine_runner, "send_dm", fake_send)
    monkeypatch.setattr("lattice.llm.router.run_agent", fake_agent)

    row = _routine(
        type="ai_review",
        instruction="review recovery",
        chattiness="only_notable",
        reminder_text=None,
    )
    db_session.add(row)
    await db_session.commit()

    result = await run_routine(db_session, row)

    assert sent == []  # sentinel → no DM
    assert result.suppressed is True
    assert result.sent is False
    assert row.last_run_at is not None


@pytest.mark.asyncio
async def test_only_notable_sends_when_notable(db_session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    sent: list[str] = []

    async def fake_send(content: str) -> bool:
        sent.append(content)
        return True

    class _Result:
        reply = "Recovery dropped 18% below baseline — ease off today."

    async def fake_agent(session, *, history, user_message):  # type: ignore[no-untyped-def]
        return _Result()

    monkeypatch.setattr(routine_runner, "send_dm", fake_send)
    monkeypatch.setattr("lattice.llm.router.run_agent", fake_agent)

    row = _routine(
        type="ai_review",
        instruction="review recovery",
        chattiness="only_notable",
        reminder_text=None,
    )
    db_session.add(row)
    await db_session.commit()

    result = await run_routine(db_session, row)

    assert len(sent) == 1
    assert "Recovery dropped" in sent[0]
    assert result.suppressed is False
    assert result.sent is True
