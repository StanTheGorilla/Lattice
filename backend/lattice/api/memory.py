"""Persistent agent memory endpoints.

CRUD over the `user_memory` table. The chat agent writes here via its
`remember` / `update_memory` / `forget` tools; this router lets the web UI
view and manage the same notes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import UserMemory
from lattice.schemas.memory import (
    MemoryCreate,
    MemoryListResponse,
    MemoryOut,
    MemoryPatch,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _not_found(memory_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"memory {memory_id} not found"},
    )


@router.get("", response_model=MemoryListResponse)
async def list_memory(
    session: AsyncSession = Depends(get_session),
) -> MemoryListResponse:
    total = (await session.execute(select(func.count(UserMemory.id)))).scalar_one()
    stmt = select(UserMemory).order_by(UserMemory.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return MemoryListResponse(
        items=[MemoryOut.from_row(r) for r in rows], total=int(total),
    )


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(
    payload: MemoryCreate,
    session: AsyncSession = Depends(get_session),
) -> MemoryOut:
    now = _now_iso()
    row = UserMemory(content=payload.content.strip(), created_at=now, updated_at=now)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return MemoryOut.from_row(row)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def patch_memory(
    memory_id: int,
    payload: MemoryPatch,
    session: AsyncSession = Depends(get_session),
) -> MemoryOut:
    row = await session.get(UserMemory, memory_id)
    if row is None:
        raise _not_found(memory_id)
    row.content = payload.content.strip()
    row.updated_at = _now_iso()
    await session.commit()
    await session.refresh(row)
    return MemoryOut.from_row(row)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(UserMemory, memory_id)
    if row is None:
        raise _not_found(memory_id)
    await session.delete(row)
    await session.commit()
