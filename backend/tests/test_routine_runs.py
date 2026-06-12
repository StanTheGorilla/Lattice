"""Tests for P3-2 routine run history recording."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from lattice.functions import routine_runner
from lattice.functions.routine_runner import NOTABLE_SENTINEL, run_routine
from lattice.models import Routine, RoutineRun


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


async def _runs(session) -> list[RoutineRun]:
    return list((await session.execute(select(RoutineRun))).scalars().all())


@pytest.mark.asyncio
async def test_reminder_records_sent_run(db_session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake_send(content: str) -> bool:
        return True

    monkeypatch.setattr(routine_runner, "send_dm", fake_send)
    row = _routine(reminder_text="drink water")
    db_session.add(row)
    await db_session.commit()

    await run_routine(db_session, row)
    await db_session.commit()

    runs = await _runs(db_session)
    assert len(runs) == 1
    assert runs[0].routine_id == row.id
    assert runs[0].sent is True
    assert runs[0].suppressed is False
    assert runs[0].reply_excerpt == "drink water"


@pytest.mark.asyncio
async def test_suppressed_run_recorded(db_session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake_send(content: str) -> bool:
        return True

    class _Result:
        reply = NOTABLE_SENTINEL

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

    await run_routine(db_session, row)
    await db_session.commit()

    runs = await _runs(db_session)
    assert len(runs) == 1
    assert runs[0].sent is False
    assert runs[0].suppressed is True
