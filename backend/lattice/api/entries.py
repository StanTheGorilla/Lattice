"""Entries endpoints (SPEC §5.2).

Generic event log. Per-type validation lives in `schemas/entries.py`. The API
layer runs that validation before persisting and stores the JSON-serialised
data column verbatim.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import SessionLocal, get_session
from lattice.models import Entry
from lattice.schemas.entries import (
    EntryCreate,
    EntryListResponse,
    EntryOut,
    EntryPatch,
    validate_data_for_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entries", tags=["entries"], dependencies=[Depends(require_auth)])


async def _estimate_and_patch(entry_id: int) -> None:
    """Background task: call DeepSeek for nutrition and patch the entry row."""
    try:
        from lattice.functions.nutrition import estimate_nutrition
        async with SessionLocal() as session:
            row = await session.get(Entry, entry_id)
            if row is None or row.type != "food":
                return
            data_dict = json.loads(row.data)
            if data_dict.get("nutrition"):
                return  # already has nutrition, skip
            description = data_dict.get("description", "")
            grams = data_dict.get("grams")
            if not description:
                return
            est = await estimate_nutrition(description, grams)
            if est is not None:
                data_dict["nutrition"] = est.to_dict()
                row.data = json.dumps(data_dict)
                await session.commit()
                logger.info("nutrition estimated for entry %d: %.0f kcal", entry_id, est.calories)
            else:
                logger.warning("nutrition estimation returned None for entry %d (%r)", entry_id, description)
    except Exception:
        logger.warning("background nutrition estimation failed for entry %d", entry_id, exc_info=True)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _validation_error(exc: ValidationError | ValueError) -> HTTPException:
    detail: dict[str, object] = {
        "error": "invalid_data",
        "message": "entry data failed schema validation",
    }
    if isinstance(exc, ValidationError):
        detail["details"] = exc.errors()
    else:
        detail["details"] = str(exc)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


@router.get("", response_model=EntryListResponse)
async def list_entries(
    type: str | None = Query(default=None, description="Filter by entry type"),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> EntryListResponse:
    where = []
    if type is not None:
        where.append(Entry.type == type)
    if from_ is not None:
        where.append(Entry.timestamp >= from_)
    if to is not None:
        where.append(Entry.timestamp <= to)

    total_stmt = select(func.count(Entry.id))
    if where:
        total_stmt = total_stmt.where(*where)
    total = (await session.execute(total_stmt)).scalar_one()

    stmt = select(Entry)
    if where:
        stmt = stmt.where(*where)
    stmt = stmt.order_by(Entry.timestamp.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()

    return EntryListResponse(
        items=[EntryOut.from_row(r) for r in rows], total=int(total),
    )


@router.post("", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: EntryCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    try:
        validated = validate_data_for_type(payload.type, payload.data)
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc) from exc

    now = _now_iso()
    timestamp = payload.timestamp or now
    row = Entry(
        timestamp=timestamp,
        logged_at=now,
        type=payload.type,
        data=json.dumps(validated.model_dump(exclude={"type"})),
        source=payload.source,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    # Queue nutrition estimation after response — never blocks the save
    if payload.type == "food":
        background_tasks.add_task(_estimate_and_patch, row.id)

    return EntryOut.from_row(row)


@router.patch("/{entry_id}", response_model=EntryOut)
async def patch_entry(
    entry_id: int,
    payload: EntryPatch,
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    row = await session.get(Entry, entry_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"entry {entry_id} not found"},
        )

    if payload.timestamp is not None:
        row.timestamp = payload.timestamp

    if payload.data is not None:
        try:
            validated = validate_data_for_type(row.type, payload.data)
        except (ValidationError, ValueError) as exc:
            raise _validation_error(exc) from exc
        row.data = json.dumps(validated.model_dump(exclude={"type"}))

    await session.commit()
    await session.refresh(row)
    return EntryOut.from_row(row)


@router.get("/{entry_id}/markers")
async def get_entry_markers(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict:
    from lattice.functions.entry_markers import compute_entry_markers
    result = await compute_entry_markers(session, entry_id, settings.timezone)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": result["error"], "entry_id": entry_id},
        )
    return result


@router.post("/{entry_id}/estimate-nutrition", response_model=EntryOut)
async def estimate_entry_nutrition(
    entry_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> EntryOut:
    """Re-trigger nutrition estimation for a food entry that has none yet."""
    row = await session.get(Entry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    if row.type != "food":
        raise HTTPException(status_code=400, detail="only food entries support nutrition estimation")
    # Clear existing nutrition so background task doesn't skip it
    data_dict = json.loads(row.data)
    data_dict.pop("nutrition", None)
    row.data = json.dumps(data_dict)
    await session.commit()
    await session.refresh(row)
    background_tasks.add_task(_estimate_and_patch, entry_id)
    return EntryOut.from_row(row)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(Entry, entry_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"entry {entry_id} not found"},
        )
    await session.delete(row)
    await session.commit()
