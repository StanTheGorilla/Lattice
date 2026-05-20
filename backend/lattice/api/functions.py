"""Functions endpoints (SPEC §5.5)."""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.functions.advisor import compute_advisor
from lattice.functions.caffeine import compute_caffeine_status
from lattice.functions.habits_adherence import compute_habit_adherence
from lattice.functions.readiness import compute_readiness
from lattice.functions.sleep_window import compute_sleep_window
from lattice.functions.training_rec import compute_training_rec
from lattice.functions.work_windows import compute_work_windows
from lattice.schemas.functions import (
    AdvisorIntent,
    AdvisorOutput,
    CaffeineStatusOutput,
    HabitAdherenceOutput,
    ReadinessOutput,
    SleepWindowOutput,
    TrainingRecOutput,
    WorkWindowsOutput,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/functions", tags=["functions"], dependencies=[Depends(require_auth)],
)


def _parse_date_or_today(value: str | None, tz: str) -> date:
    if value is None:
        return datetime.now(ZoneInfo(tz)).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_date",
                "message": f"expected YYYY-MM-DD, got {value!r}",
            },
        ) from exc


@router.get("/readiness", response_model=ReadinessOutput)
async def get_readiness(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> ReadinessOutput:
    target = _parse_date_or_today(date_, settings.timezone)
    return await compute_readiness(session, target=target, tz=settings.timezone)


@router.get("/work_windows", response_model=WorkWindowsOutput)
async def get_work_windows(
    date_: str | None = Query(default=None, alias="date"),
    min_minutes: int = Query(default=60, ge=15, le=480),
    session: AsyncSession = Depends(get_session),
) -> WorkWindowsOutput:
    target = _parse_date_or_today(date_, settings.timezone)
    readiness = await compute_readiness(session, target=target, tz=settings.timezone)
    return await compute_work_windows(
        session,
        target=target,
        tz=settings.timezone,
        min_minutes=min_minutes,
        readiness_score=readiness.score,
    )


@router.get("/training_recommendation", response_model=TrainingRecOutput)
async def get_training_recommendation(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> TrainingRecOutput:
    target = _parse_date_or_today(date_, settings.timezone)
    readiness = await compute_readiness(session, target=target, tz=settings.timezone)
    return await compute_training_rec(
        session,
        target=target,
        tz=settings.timezone,
        readiness_score=readiness.score,
    )


@router.get("/sleep_window", response_model=SleepWindowOutput)
async def get_sleep_window(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> SleepWindowOutput:
    target = _parse_date_or_today(date_, settings.timezone)
    return await compute_sleep_window(session, target=target, tz=settings.timezone)


@router.get("/caffeine_status", response_model=CaffeineStatusOutput)
async def get_caffeine_status(
    at: str | None = Query(default=None, description="ISO 8601 instant; defaults to now"),
    session: AsyncSession = Depends(get_session),
) -> CaffeineStatusOutput:
    zone = ZoneInfo(settings.timezone)
    if at is None:
        now = datetime.now(zone)
    else:
        try:
            now = datetime.fromisoformat(at)
            if now.tzinfo is None:
                now = now.replace(tzinfo=zone)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "invalid_at",
                    "message": f"expected ISO 8601, got {at!r}",
                },
            ) from exc
    return await compute_caffeine_status(session, at=now, tz=settings.timezone)


@router.get("/advisor", response_model=AdvisorOutput)
async def get_advisor(
    intent: AdvisorIntent = Query(...),
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> AdvisorOutput:
    target = _parse_date_or_today(date_, settings.timezone)
    return await compute_advisor(
        session, intent=intent, target=target, tz=settings.timezone,
    )


@router.get(
    "/habits/adherence",
    response_model=HabitAdherenceOutput,
    response_model_by_alias=True,
)
async def get_habit_adherence(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> HabitAdherenceOutput:
    zone = ZoneInfo(settings.timezone)
    today = datetime.now(zone).date()
    from_d = _parse_date_or_today(from_, settings.timezone) if from_ else today.replace(day=1)
    to_d = _parse_date_or_today(to, settings.timezone) if to else today
    if from_d > to_d:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_range", "message": "from > to"},
        )
    return await compute_habit_adherence(
        session, from_=from_d, to=to_d, today=today,
    )


# ---------- F10 analytics ----------

@router.get("/analytics/allostatic_load")
async def get_allostatic_load(
    session: AsyncSession = Depends(get_session),
) -> dict:
    from lattice.functions.allostatic_load import compute_allostatic_load
    return await compute_allostatic_load(session)


@router.get("/analytics/changepoints")
async def get_changepoints(
    metric: str = Query(...),
    days: int = Query(default=90, ge=21, le=365),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from lattice.functions.changepoint import detect_changepoints
    return await detect_changepoints(session, metric_name=metric, days=days)


@router.get("/analytics/lagged_correlation")
async def get_lagged_correlation(
    metric_a: str = Query(...),
    metric_b: str = Query(...),
    days: int = Query(default=90, ge=21, le=365),
    max_lag: int = Query(default=5, ge=1, le=14),
    session: AsyncSession = Depends(get_session),
) -> dict:
    from lattice.functions.lagged_correlate import compute_lagged_correlation
    return await compute_lagged_correlation(
        session, metric_a=metric_a, metric_b=metric_b, max_lag=max_lag, days=days
    )
