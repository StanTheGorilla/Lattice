"""Recovery analysis — 'how does my body respond the day after X?'

For each occurrence of a workout of a given `kind` in the lookback window,
read the next-day HRV, RHR, and readiness, and compare to the personal
baseline (rolling 14-day mean preceding the workout). Returns aggregate
deltas + per-occurrence rows so the LLM can talk about specific instances.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.baselines import compute_baseline, metric_on_date
from lattice.functions.readiness import compute_readiness
from lattice.models import Workout


async def recovery_after(
    session: AsyncSession,
    activity_kind: str,
    lookback_days: int = 90,
) -> dict[str, Any]:
    """Next-day HRV / RHR / readiness deltas after each `kind` workout."""
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    from_dt = now - timedelta(days=lookback_days)
    stmt = (
        select(Workout)
        .where(Workout.kind == activity_kind)
        .where(Workout.start >= from_dt.isoformat())
        .order_by(Workout.start.asc())
    )
    workouts = (await session.execute(stmt)).scalars().all()

    rows: list[dict[str, Any]] = []
    hrv_deltas: list[float] = []
    rhr_deltas: list[float] = []
    readiness_deltas: list[float] = []

    for w in workouts:
        try:
            start_dt = datetime.fromisoformat(w.start)
        except ValueError:
            continue
        workout_day = start_dt.astimezone(tz).date()
        next_day = workout_day + timedelta(days=1)

        # Next-day measurements.
        hrv_next = await metric_on_date(session, "hrv_overnight_avg", next_day, settings.timezone)
        rhr_next = await metric_on_date(session, "resting_hr", next_day, settings.timezone)

        # Baselines preceding the workout (excludes the workout-day onwards).
        hrv_base = await compute_baseline(
            session, "hrv_overnight_avg", days=14, before=workout_day, tz=settings.timezone,
        )
        rhr_base = await compute_baseline(
            session, "resting_hr", days=14, before=workout_day, tz=settings.timezone,
        )

        row: dict[str, Any] = {
            "workout_id": w.id,
            "kind": w.kind,
            "start": w.start,
            "duration_min": w.duration_min,
            "training_effect": w.training_effect,
        }

        if hrv_next is not None and hrv_base.mean is not None:
            delta = float(hrv_next.value) - hrv_base.mean
            row["hrv_next_day"] = float(hrv_next.value)
            row["hrv_baseline"] = round(hrv_base.mean, 2)
            row["hrv_delta_pct"] = round(delta / hrv_base.mean * 100.0, 2) if hrv_base.mean else None
            hrv_deltas.append(row["hrv_delta_pct"]) if row["hrv_delta_pct"] is not None else None

        if rhr_next is not None and rhr_base.mean is not None:
            delta = float(rhr_next.value) - rhr_base.mean
            row["rhr_next_day"] = float(rhr_next.value)
            row["rhr_baseline"] = round(rhr_base.mean, 2)
            row["rhr_delta_pct"] = round(delta / rhr_base.mean * 100.0, 2) if rhr_base.mean else None
            rhr_deltas.append(row["rhr_delta_pct"]) if row["rhr_delta_pct"] is not None else None

        # Readiness on the next day — compute deterministically (free, accurate).
        try:
            readiness = await compute_readiness(
                session, target=next_day, tz=settings.timezone,
            )
            if readiness.score is not None:
                row["readiness_next_day"] = readiness.score
                readiness_deltas.append(readiness.score)
        except Exception:  # noqa: BLE001 — fail-soft
            pass

        rows.append(row)

    def _med(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 2) if xs else None

    return {
        "kind": activity_kind,
        "lookback_days": lookback_days,
        "n_workouts": len(workouts),
        "n_with_next_day_data": len([r for r in rows if "hrv_next_day" in r or "rhr_next_day" in r]),
        "median_hrv_delta_pct": _med(hrv_deltas),
        "median_rhr_delta_pct": _med(rhr_deltas),
        "median_readiness_next_day": _med(readiness_deltas),
        "low_confidence": len(rows) < 5,
        "occurrences": rows[-20:],  # cap to keep payload tight
    }
