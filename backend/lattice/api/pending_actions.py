"""Open-commitments endpoints.

CRUD over the `pending_actions` table. The chat agent writes here via its
pending-action tools; this router lets the web UI view, resolve, edit, and
delete the same commitments.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import PendingAction
from lattice.schemas.pending_action import (
    PendingActionCreate,
    PendingActionListResponse,
    PendingActionOut,
    PendingActionPatch,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pending-actions",
    tags=["pending-actions"],
    dependencies=[Depends(require_auth)],
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _not_found(action_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"pending action {action_id} not found"},
    )


@router.get("", response_model=PendingActionListResponse)
async def list_pending_actions(
    session: AsyncSession = Depends(get_session),
) -> PendingActionListResponse:
    total = (await session.execute(select(func.count(PendingAction.id)))).scalar_one()
    stmt = select(PendingAction).order_by(PendingAction.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return PendingActionListResponse(
        items=[PendingActionOut.from_row(r) for r in rows], total=int(total),
    )


@router.post("", response_model=PendingActionOut, status_code=status.HTTP_201_CREATED)
async def create_pending_action(
    payload: PendingActionCreate,
    session: AsyncSession = Depends(get_session),
) -> PendingActionOut:
    now = _now_iso()
    detail = payload.detail.strip() if payload.detail else None
    row = PendingAction(
        summary=payload.summary.strip(),
        detail=detail,
        status="open",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return PendingActionOut.from_row(row)


@router.patch("/{action_id}", response_model=PendingActionOut)
async def patch_pending_action(
    action_id: int,
    payload: PendingActionPatch,
    session: AsyncSession = Depends(get_session),
) -> PendingActionOut:
    row = await session.get(PendingAction, action_id)
    if row is None:
        raise _not_found(action_id)
    fields = payload.model_dump(exclude_unset=True)
    if "summary" in fields and fields["summary"] is not None:
        row.summary = fields["summary"].strip()
    if "detail" in fields:
        row.detail = fields["detail"].strip() if fields["detail"] else None
    if "status" in fields and fields["status"] is not None:
        row.status = fields["status"]
    row.updated_at = _now_iso()
    await session.commit()
    await session.refresh(row)
    return PendingActionOut.from_row(row)


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pending_action(
    action_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(PendingAction, action_id)
    if row is None:
        raise _not_found(action_id)
    await session.delete(row)
    await session.commit()
