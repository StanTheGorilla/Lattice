"""F3 — Training Recommendation (SPEC §6).

Rules (evaluate top-to-bottom, first match wins):
  1. readiness < 40 → rest
  2. ac_ratio > 1.5 → easy
  3. ac_ratio < 0.8 AND readiness > 60 → moderate
  4. readiness > 75 AND days_since_hard ≥ 2 → hard
  5. else → moderate

Then: cap one level (hard→moderate, moderate→easy) if today's meeting_hours > 4.

`ac_ratio` = acute / chronic. If chronic == 0: rule 1 still wins on low readiness,
otherwise we return easy with low confidence (insufficient training history).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import latest_metric, parse_iso
from lattice.models import CalendarCache, Entry, Metric
from lattice.schemas.functions import TrainingRec, TrainingRecOutput

# Ordered cap-down chain.
_CAP_DOWN: dict[TrainingRec, TrainingRec] = {
    "hard": "moderate",
    "moderate": "easy",
    "easy": "easy",
    "rest": "rest",
}


async def _last_hard_workout_date(
    session: AsyncSession, *, target: date, tz: str,
) -> date | None:
    """Look back 30 days for the most recent training_status=PRODUCTIVE or
    a workout_manual entry with intensity=high. Returns its local date."""
    zone = ZoneInfo(tz)
    earliest = datetime.combine(target - timedelta(days=30), datetime.min.time(), tzinfo=zone)

    # Manual workouts
    stmt = (
        select(Entry)
        .where(
            Entry.type == "workout_manual",
            Entry.timestamp >= earliest.isoformat(),
            Entry.timestamp < datetime.combine(target, datetime.min.time(), tzinfo=zone).isoformat(),
        )
        .order_by(Entry.timestamp.desc())
    )
    for row in (await session.execute(stmt)).scalars().all():
        # Parse data JSON without importing the full schema.
        import json as _json
        try:
            data = _json.loads(row.data)
        except Exception:
            continue
        if data.get("intensity") == "high":
            return parse_iso(row.timestamp).astimezone(zone).date()
    return None


async def _meeting_hours_today(
    session: AsyncSession, *, target: date, tz: str,
) -> float:
    """Sum of meeting durations on `target` from cached calendar events
    (timed events only, since all-day vacation shouldn't count as meetings)."""
    zone = ZoneInfo(tz)
    day_start = datetime.combine(target, datetime.min.time(), tzinfo=zone)
    day_end = day_start + timedelta(days=1)

    stmt = (
        select(CalendarCache)
        .where(
            CalendarCache.is_all_day == 0,
            CalendarCache.end >= day_start.isoformat(),
            CalendarCache.start <= day_end.isoformat(),
        )
    )
    total = 0.0
    for row in (await session.execute(stmt)).scalars().all():
        try:
            s = parse_iso(row.start).astimezone(zone)
            e = parse_iso(row.end).astimezone(zone)
        except ValueError:
            continue
        # Clip to the day.
        s = max(s, day_start)
        e = min(e, day_end)
        if e > s:
            total += (e - s).total_seconds() / 3600.0
    return total


async def compute_training_rec(
    session: AsyncSession, *, target: date, tz: str, readiness_score: float | None,
) -> TrainingRecOutput:
    """Compute F3 for `target`.

    `readiness_score` may be provided by the caller (advisor flow) to avoid
    recomputing F1. If None, falls back to "moderate, low confidence."
    """
    acute_row = await latest_metric(session, "training_load_acute")
    chronic_row = await latest_metric(session, "training_load_chronic")
    acute = float(acute_row.value) if acute_row else 0.0
    chronic = float(chronic_row.value) if chronic_row else 0.0
    ac_ratio = (acute / chronic) if chronic > 0 else 0.0
    last_hard = await _last_hard_workout_date(session, target=target, tz=tz)
    days_since_hard = (target - last_hard).days if last_hard else 999
    meeting_hours = await _meeting_hours_today(session, target=target, tz=tz)
    r = float(readiness_score) if readiness_score is not None else 50.0
    rationale: list[str] = []

    # Rule cascade.
    rec: TrainingRec
    confidence: float
    if readiness_score is None:
        rationale.append("readiness unavailable, defaulting to moderate")
        rec = "moderate"
        confidence = 0.3
    elif r < 40:
        rationale.append(f"readiness {int(r)} < 40 (depleted)")
        rec = "rest"
        confidence = 0.9
    elif chronic == 0:
        rationale.append("no training-load baseline yet — easy day, low confidence")
        rec = "easy"
        confidence = 0.3
    elif ac_ratio > 1.5:
        rationale.append(f"acute:chronic ratio {ac_ratio:.2f} > 1.5 (overload risk)")
        rec = "easy"
        confidence = 0.85
    elif ac_ratio < 0.8 and r > 60:
        rationale.append(f"ac ratio {ac_ratio:.2f} < 0.8 and readiness {int(r)} > 60 (room to push)")
        rec = "moderate"
        confidence = 0.75
    elif r > 75 and days_since_hard >= 2:
        rationale.append(
            f"readiness {int(r)} > 75 and {days_since_hard}d since last hard session"
        )
        rec = "hard"
        confidence = 0.8
    else:
        rationale.append(f"default cascade — readiness {int(r)}, ac ratio {ac_ratio:.2f}")
        rec = "moderate"
        confidence = 0.55

    # Meeting cap.
    if meeting_hours > 4 and rec != "rest":
        capped = _CAP_DOWN[rec]
        if capped != rec:
            rationale.append(
                f"meeting hours {meeting_hours:.1f} > 4 → capping {rec} → {capped}"
            )
            rec = capped
            confidence = max(0.5, confidence - 0.1)

    return TrainingRecOutput(
        date=target.isoformat(),
        recommendation=rec,
        confidence=round(confidence, 2),
        rationale=rationale,
        inputs={
            "readiness": int(r) if readiness_score is not None else None,
            "acute_load": acute,
            "chronic_load": chronic,
            "ac_ratio": round(ac_ratio, 3),
            "days_since_hard": days_since_hard if last_hard else None,
            "meeting_hours": round(meeting_hours, 2),
        },
    )


__all__ = ["compute_training_rec"]
