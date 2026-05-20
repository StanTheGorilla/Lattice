"""Habit endpoints — definitions and check-ins (SPEC §4.5).

SPEC §5.x does not enumerate habit endpoints; the shape below mirrors the
entries CRUD style. F8 (adherence) lives separately under /functions in 2E.

No hard DELETE on definitions: deactivate via PATCH `active=false`. A hard
delete would cascade to historical checkins via the FK ondelete, erasing
weeks of data.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import HabitCheckin, HabitDefinition
from lattice.schemas.habits import (
    HabitCheckinCreate,
    HabitCheckinListResponse,
    HabitCheckinOut,
    HabitDefinitionCreate,
    HabitDefinitionOut,
    HabitDefinitionPatch,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/habits", tags=["habits"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _get_definition(session: AsyncSession, habit_id: int) -> HabitDefinition:
    row = await session.get(HabitDefinition, habit_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"habit {habit_id} not found"},
        )
    return row


# --------------------------------------------------------------------------- #
# Definitions
# --------------------------------------------------------------------------- #


@router.get("", response_model=list[HabitDefinitionOut])
async def list_habits(
    active: bool | None = Query(default=None, description="Filter by active flag"),
    session: AsyncSession = Depends(get_session),
) -> list[HabitDefinitionOut]:
    stmt = select(HabitDefinition)
    if active is not None:
        stmt = stmt.where(HabitDefinition.active == active)
    stmt = stmt.order_by(HabitDefinition.name.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [HabitDefinitionOut.model_validate(r) for r in rows]


@router.post("", response_model=HabitDefinitionOut, status_code=status.HTTP_201_CREATED)
async def create_habit(
    payload: HabitDefinitionCreate,
    session: AsyncSession = Depends(get_session),
) -> HabitDefinitionOut:
    row = HabitDefinition(
        name=payload.name,
        target_per_week=payload.target_per_week,
        active=payload.active,
        created_at=_now_iso(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_name",
                "message": f"habit named {payload.name!r} already exists",
            },
        ) from exc
    await session.refresh(row)
    return HabitDefinitionOut.model_validate(row)


@router.patch("/{habit_id}", response_model=HabitDefinitionOut)
async def patch_habit(
    habit_id: int,
    payload: HabitDefinitionPatch,
    session: AsyncSession = Depends(get_session),
) -> HabitDefinitionOut:
    row = await _get_definition(session, habit_id)

    if payload.name is not None:
        row.name = payload.name
    if payload.target_per_week is not None:
        row.target_per_week = payload.target_per_week
    if payload.active is not None:
        row.active = payload.active

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_name",
                "message": "name collides with another habit",
            },
        ) from exc
    await session.refresh(row)
    return HabitDefinitionOut.model_validate(row)


# --------------------------------------------------------------------------- #
# Checkins
# --------------------------------------------------------------------------- #


@router.get(
    "/{habit_id}/checkins", response_model=HabitCheckinListResponse,
)
async def list_checkins(
    habit_id: int,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> HabitCheckinListResponse:
    await _get_definition(session, habit_id)
    where = [HabitCheckin.habit_id == habit_id]
    if from_ is not None:
        where.append(HabitCheckin.date >= from_)
    if to is not None:
        where.append(HabitCheckin.date <= to)
    stmt = select(HabitCheckin).where(and_(*where)).order_by(HabitCheckin.date.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return HabitCheckinListResponse(
        items=[HabitCheckinOut.model_validate(r) for r in rows],
    )


@router.post(
    "/{habit_id}/checkins",
    response_model=HabitCheckinOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_update_checkin(
    habit_id: int,
    payload: HabitCheckinCreate,
    session: AsyncSession = Depends(get_session),
) -> HabitCheckinOut:
    """Idempotent UPSERT on (habit_id, date). Re-posting the same date
    overwrites completed/note rather than 409-ing."""
    await _get_definition(session, habit_id)
    stmt = sqlite_insert(HabitCheckin.__table__).values(
        habit_id=habit_id,
        date=payload.date,
        completed=payload.completed,
        note=payload.note,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["habit_id", "date"],
        set_={"completed": stmt.excluded.completed, "note": stmt.excluded.note},
    )
    await session.execute(stmt)
    await session.commit()

    fetched = (
        await session.execute(
            select(HabitCheckin).where(
                and_(
                    HabitCheckin.habit_id == habit_id,
                    HabitCheckin.date == payload.date,
                ),
            ),
        )
    ).scalar_one()
    return HabitCheckinOut.model_validate(fetched)


@router.delete(
    "/{habit_id}/checkins/{date}", status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_checkin(
    habit_id: int,
    date: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    await _get_definition(session, habit_id)
    row = (
        await session.execute(
            select(HabitCheckin).where(
                and_(HabitCheckin.habit_id == habit_id, HabitCheckin.date == date),
            ),
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "not_found",
                "message": f"no checkin for habit {habit_id} on {date}",
            },
        )
    await session.delete(row)
    await session.commit()
