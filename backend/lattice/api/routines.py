"""Routine CRUD + manual run (Phase B).

Routines replace the three hardcoded Discord briefs. The web UI and chat agent
create/edit/delete here; the backend scheduler (`sync/scheduler.py`) runs them
on a per-routine CronTrigger. Every mutation calls `scheduler.reschedule` /
`remove_routine_job` so live edits take effect without a restart.

`POST /{id}/run` runs a routine immediately (works even when the scheduler is
disabled in dev) so the owner can test a routine the moment they create it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.functions.routine_runner import run_routine
from lattice.models import Routine, RoutineRun
from lattice.schemas.routine import (
    RoutineIn,
    RoutineListResponse,
    RoutineOut,
    RoutinePatch,
    RoutineRunListResponse,
    RoutineRunOut,
)
from lattice.sync import scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routines", tags=["routines"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _not_found(routine_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"routine {routine_id} not found"},
    )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "invalid_routine", "message": message},
    )


@router.get("", response_model=RoutineListResponse)
async def list_routines(
    session: AsyncSession = Depends(get_session),
) -> RoutineListResponse:
    total = (await session.execute(select(func.count(Routine.id)))).scalar_one()
    stmt = select(Routine).order_by(Routine.hour.asc(), Routine.minute.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return RoutineListResponse(
        items=[RoutineOut.from_row(r) for r in rows], total=int(total),
    )


@router.get("/runs", response_model=RoutineRunListResponse)
async def list_routine_runs(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> RoutineRunListResponse:
    """Recent routine executions, newest first (P3-2)."""
    limit = max(1, min(limit, 100))
    stmt = (
        select(RoutineRun)
        .order_by(RoutineRun.fired_at.desc(), RoutineRun.id.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return RoutineRunListResponse(items=[RoutineRunOut.model_validate(r) for r in rows])


@router.post("", response_model=RoutineOut, status_code=status.HTTP_201_CREATED)
async def create_routine(
    payload: RoutineIn,
    session: AsyncSession = Depends(get_session),
) -> RoutineOut:
    row = Routine(
        name=payload.name.strip(),
        type=payload.type,
        hour=payload.hour,
        minute=payload.minute,
        weekday_mask=payload.weekday_mask,
        instruction=(payload.instruction or None),
        chattiness=payload.chattiness,
        reminder_text=(payload.reminder_text or None),
        enabled=payload.enabled,
        last_run_at=None,
        created_at=_now_iso(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await scheduler.reschedule(row.id)
    return RoutineOut.from_row(row)


@router.patch("/{routine_id}", response_model=RoutineOut)
async def patch_routine(
    routine_id: int,
    payload: RoutinePatch,
    session: AsyncSession = Depends(get_session),
) -> RoutineOut:
    row = await session.get(Routine, routine_id)
    if row is None:
        raise _not_found(routine_id)

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field in ("name",) and isinstance(value, str):
            value = value.strip()
        setattr(row, field, value)

    # Re-check type coherence against the merged row.
    if row.type == "reminder" and not (row.reminder_text and row.reminder_text.strip()):
        raise _bad_request("reminder routines require reminder_text")
    if row.type == "ai_review" and not (row.instruction and row.instruction.strip()):
        raise _bad_request("ai_review routines require instruction")

    await session.commit()
    await session.refresh(row)
    await scheduler.reschedule(row.id)
    return RoutineOut.from_row(row)


@router.delete("/{routine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routine(
    routine_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(Routine, routine_id)
    if row is None:
        raise _not_found(routine_id)
    await session.delete(row)
    await session.commit()
    scheduler.remove_routine_job(routine_id)


@router.post("/{routine_id}/run", response_model=RoutineOut)
async def run_routine_now(
    routine_id: int,
    session: AsyncSession = Depends(get_session),
) -> RoutineOut:
    """Run a routine immediately, regardless of schedule or enabled state."""
    row = await session.get(Routine, routine_id)
    if row is None:
        raise _not_found(routine_id)
    result = await run_routine(session, row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "routine %s manual run: sent=%s suppressed=%s",
        routine_id, result.sent, result.suppressed,
    )
    return RoutineOut.from_row(row)
