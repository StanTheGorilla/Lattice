"""Weekly report endpoints (SPEC §5.7).

Three routes:
  GET  /reports/weekly/latest       → latest WeeklyReport (404 if none)
  GET  /reports/weekly?week=YYYY-Www → that specific week (404 if missing)
  POST /reports/weekly/generate     → compute Stage A+B for `?week=` (or
       current ISO week if omitted). Overwrites existing row per 2I decision.

`POST .../generate` is intentionally idempotent — re-running always reflects
the latest pass.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.functions.weekly_report import (
    generate_weekly_report,
    get_latest_weekly_report,
    get_weekly_report,
    list_weekly_report_weeks,
)
from lattice.schemas.reports import WeeklyReportOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(require_auth)])

_ISO_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def _parse_iso_week_or_422(value: str) -> tuple[int, int]:
    m = _ISO_WEEK_RE.match(value)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_week",
                "message": f"expected YYYY-Www, got {value!r}",
            },
        )
    return int(m.group(1)), int(m.group(2))


def _target_for_iso_week(value: str) -> date:
    """Convert 'YYYY-Www' to a date that falls within that ISO week (Monday)."""
    year, week = _parse_iso_week_or_422(value)
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_week", "message": str(exc)},
        ) from exc


@router.get("/weekly/index", response_model=list[str])
async def list_weeks(
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Return iso_weeks (newest first) for which a report exists."""
    return await list_weekly_report_weeks(session)


@router.get("/weekly/latest", response_model=WeeklyReportOut)
async def get_latest(
    session: AsyncSession = Depends(get_session),
) -> WeeklyReportOut:
    row = await get_latest_weekly_report(session)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_reports", "message": "no weekly reports yet"},
        )
    return WeeklyReportOut.from_row(row)


@router.get("/weekly", response_model=WeeklyReportOut)
async def get_by_week(
    week: str = Query(..., description="ISO week, e.g. 2026-W19"),
    session: AsyncSession = Depends(get_session),
) -> WeeklyReportOut:
    _parse_iso_week_or_422(week)  # validate shape
    row = await get_weekly_report(session, week)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"no report for {week}"},
        )
    return WeeklyReportOut.from_row(row)


@router.post("/weekly/generate", response_model=WeeklyReportOut)
async def generate(
    week: str | None = Query(default=None, description="ISO week, e.g. 2026-W19; default = current"),
    session: AsyncSession = Depends(get_session),
) -> WeeklyReportOut:
    if week is None:
        today = datetime.now(ZoneInfo(settings.timezone)).date()
        target = today
    else:
        target = _target_for_iso_week(week)
    row = await generate_weekly_report(session, target=target, tz=settings.timezone)
    return WeeklyReportOut.from_row(row)
