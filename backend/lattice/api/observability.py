"""LLM observability endpoint (P3-1).

Exposes aggregated daily token usage + a rough cost estimate from the
`llm_usage` table for the web UI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.functions.llm_observability import get_llm_usage_summary

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(require_auth)],
)


@router.get("/llm-usage")
async def llm_usage(
    days: int = Query(default=30, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await get_llm_usage_summary(session, days=days)
