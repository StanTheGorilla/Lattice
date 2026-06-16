"""AI-journal endpoints.

CRUD over the `ai_journal` table. The chat agent writes self-guidance here via
its journal tools; this router lets the web UI view, edit, retire (toggle
`active`), and delete those entries.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import AIJournal
from lattice.schemas.ai_journal import (
    AIJournalCreate,
    AIJournalListResponse,
    AIJournalOut,
    AIJournalPatch,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/journal", tags=["journal"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _not_found(entry_id: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "not_found", "message": f"journal entry {entry_id} not found"},
    )


@router.get("", response_model=AIJournalListResponse)
async def list_journal(
    session: AsyncSession = Depends(get_session),
) -> AIJournalListResponse:
    # Ordered by weight desc then updated_at desc: the entries that most shape
    # the assistant's behaviour surface first.
    total = (await session.execute(select(func.count(AIJournal.id)))).scalar_one()
    stmt = select(AIJournal).order_by(
        AIJournal.weight.desc(), AIJournal.updated_at.desc(),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return AIJournalListResponse(
        items=[AIJournalOut.from_row(r) for r in rows], total=int(total),
    )


@router.post("", response_model=AIJournalOut, status_code=status.HTTP_201_CREATED)
async def create_journal(
    payload: AIJournalCreate,
    session: AsyncSession = Depends(get_session),
) -> AIJournalOut:
    now = _now_iso()
    trigger = payload.trigger.strip() if payload.trigger else None
    row = AIJournal(
        entry=payload.entry.strip(),
        kind=payload.kind,
        trigger=trigger,
        weight=1,
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return AIJournalOut.from_row(row)


@router.patch("/{entry_id}", response_model=AIJournalOut)
async def patch_journal(
    entry_id: int,
    payload: AIJournalPatch,
    session: AsyncSession = Depends(get_session),
) -> AIJournalOut:
    row = await session.get(AIJournal, entry_id)
    if row is None:
        raise _not_found(entry_id)
    fields = payload.model_dump(exclude_unset=True)
    if "entry" in fields and fields["entry"] is not None:
        row.entry = fields["entry"].strip()
    if "kind" in fields and fields["kind"] is not None:
        row.kind = fields["kind"]
    if "trigger" in fields:
        row.trigger = fields["trigger"].strip() if fields["trigger"] else None
    if "active" in fields and fields["active"] is not None:
        row.active = fields["active"]
    row.updated_at = _now_iso()
    await session.commit()
    await session.refresh(row)
    return AIJournalOut.from_row(row)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(AIJournal, entry_id)
    if row is None:
        raise _not_found(entry_id)
    await session.delete(row)
    await session.commit()
