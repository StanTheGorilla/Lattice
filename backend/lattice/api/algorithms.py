"""AI-authored algorithms endpoints (Phase 2L-a).

Read-only for the web UI — the AI creates algorithms via the chat tools.
Users can browse and delete algorithms here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import CustomAlgorithm

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/algorithms",
    tags=["algorithms"],
    dependencies=[Depends(require_auth)],
)


class AlgorithmOut(BaseModel):
    id: int
    name: str
    description: str
    data_requirements: dict[str, Any]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: CustomAlgorithm) -> "AlgorithmOut":
        try:
            dr = json.loads(row.data_requirements)
        except (json.JSONDecodeError, TypeError):
            dr = {}
        return cls(
            id=row.id,
            name=row.name,
            description=row.description,
            data_requirements=dr,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@router.get("", response_model=list[AlgorithmOut])
async def list_algorithms(
    session: AsyncSession = Depends(get_session),
) -> list[AlgorithmOut]:
    stmt = select(CustomAlgorithm).order_by(CustomAlgorithm.created_at.desc())
    rows = list((await session.execute(stmt)).scalars().all())
    return [AlgorithmOut.from_row(r) for r in rows]


@router.delete("/{name}", status_code=204)
async def delete_algorithm(
    name: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await session.execute(
            select(CustomAlgorithm).where(CustomAlgorithm.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": f"Algorithm '{name}' not found"},
        )
    await session.delete(row)
    await session.commit()
