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
from lattice.functions.recommendation_store import (
    clear_sleep_recommendation,
    get_active_sleep_recommendation,
)
from lattice.functions.sleep_window import compute_sleep_window
from lattice.functions.training_rec import compute_training_rec
from lattice.functions.work_windows import compute_work_windows
from lattice.llm.router import run_agent
from lattice.schemas.functions import (
    AdvisorIntent,
    AdvisorOutput,
    CaffeineStatusOutput,
    HabitAdherenceOutput,
    ReadinessOutput,
    TrainingRecOutput,
    WorkWindowsOutput,
)
from lattice.schemas.recommendation import SleepRecommendation

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/functions", tags=["functions"], dependencies=[Depends(require_auth)],
)


def _hhmm(iso: str) -> str:
    """Extract HH:MM from an ISO 8601 datetime for compact prompt text."""
    return iso[11:16] if "T" in iso and len(iso) >= 16 else iso


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


@router.get("/sleep_window", response_model=SleepRecommendation)
async def get_sleep_window(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> SleepRecommendation:
    """The stored sleep recommendation: the AI's decision if it has made one for
    this date, else an F4 formula seed. The website Today page and the evening
    brief both read this endpoint, so they converge on the same numbers."""
    target = _parse_date_or_today(date_, settings.timezone)
    return await get_active_sleep_recommendation(
        session, target=target, tz=settings.timezone,
    )


@router.post("/sleep_window/regenerate", response_model=SleepRecommendation)
async def regenerate_sleep_window(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> SleepRecommendation:
    """Ask the AI to decide and persist tonight's sleep window, then return it.

    This is the Today page's "Regenerate with AI" action. It runs the chat agent
    in-process with a fixed instruction to weigh recovery, calendar, and healthy
    sleep guidelines (rather than blindly echoing the F4 median, which can imply
    an unhealthily short night or a very late bedtime) and to persist its decision
    via set_sleep_recommendation. The Today card and evening brief then read the
    same AI row.
    """
    target = _parse_date_or_today(date_, settings.timezone)
    # Compute the deterministic F4 window FRESH (not the stored row, which may
    # already be a prior AI decision) so the AI can see exactly what the
    # algorithm chose and why before forming its own answer.
    f4 = await compute_sleep_window(session, target=target, tz=settings.timezone)
    instruction = (
        "Here is what the deterministic F4 sleep algorithm just computed, and "
        "the reasoning behind each number:\n"
        f"- Bedtime {_hhmm(f4.bedtime)}, wake {_hhmm(f4.wake_time)}, "
        f"target {f4.target_duration_min:.0f} min.\n"
        f"- Wake derived from: {f4.inputs.get('wake_derivation')}.\n"
        f"- Baseline duration {f4.inputs.get('baseline_duration_min')} min — the "
        "median of my sleep on nights followed by good readiness, from "
        f"{f4.inputs.get('qualifying_days_for_baseline')} qualifying days.\n"
        f"- Recovery adjustment {f4.inputs.get('recovery_adjustment_min')} min "
        f"({f4.inputs.get('recovery_basis') or 'today near baseline'}).\n"
        f"- Flags: {'; '.join(f4.flags) or 'none'}.\n\n"
        "Use the algorithm's numbers and reasoning as your starting point. Agree "
        "with it where it is sound, but OVERRIDE it where it is unhealthy — e.g. "
        "if it echoes an unhealthily short median or an unreasonably late bedtime "
        "for my age and situation. Weigh my recovery signals (HRV, stress, body "
        "battery) and tomorrow's first calendar commitment too. Then persist your "
        "decision by calling set_sleep_recommendation with bedtime, wake_time, and "
        "a concise one-sentence rationale that says how your choice relates to the "
        "algorithm's. Reply with just the bedtime, wake time, and why."
    )
    try:
        await run_agent(session, history=[], user_message=instruction)
    except Exception as exc:  # noqa: BLE001 — surface a clean 502 to the client
        logger.warning("sleep_window regenerate failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "ai_unavailable",
                "message": "The AI could not generate a sleep window right now.",
            },
        ) from exc
    return await get_active_sleep_recommendation(
        session, target=target, tz=settings.timezone,
    )


@router.post("/sleep_window/revert", response_model=SleepRecommendation)
async def revert_sleep_window(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> SleepRecommendation:
    """Discard any AI sleep decision for the date and fall back to the F4
    algorithm. Returns the fresh deterministic (`formula`) recommendation."""
    target = _parse_date_or_today(date_, settings.timezone)
    await clear_sleep_recommendation(session, target=target)
    return await get_active_sleep_recommendation(
        session, target=target, tz=settings.timezone,
    )


@router.get("/sleep_window/formula", response_model=SleepRecommendation)
async def get_sleep_window_formula(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> SleepRecommendation:
    """The live deterministic F4 window, computed fresh and NOT persisted.

    Powers the Today card's Algorithm tab so it can be reloaded independently of
    the stored (possibly AI-owned) recommendation. This never overwrites the AI
    decision — it is a read-only preview of what the algorithm currently says.
    """
    target = _parse_date_or_today(date_, settings.timezone)
    f4 = await compute_sleep_window(session, target=target, tz=settings.timezone)
    wake_deriv = f4.inputs.get("wake_derivation")
    rationale_parts: list[str] = []
    if isinstance(wake_deriv, str):
        rationale_parts.append(f"Wake: {wake_deriv}.")
    if f4.flags:
        rationale_parts.append("Flags: " + "; ".join(f4.flags) + ".")
    rationale = " ".join(rationale_parts) or "Derived from the F4 sleep-window formula."
    return SleepRecommendation(
        date=f4.date,
        bedtime=f4.bedtime,
        wake_time=f4.wake_time,
        target_duration_min=f4.target_duration_min,
        flags=f4.flags,
        inputs=f4.inputs,
        source="formula",
        rationale=rationale,
        author="f4_live",
    )


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
