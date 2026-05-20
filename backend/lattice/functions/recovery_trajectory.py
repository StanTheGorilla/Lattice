"""Recovery trajectory fingerprint.

After each workout of a given kind, track how HRV, RHR, and readiness
change day-by-day for up to 5 days. Average the trajectories to build the
user's personal 'recovery fingerprint'. Compare recent workouts against
the fingerprint to flag unusual recoveries.

Longer description of approach:
- Find all workouts of the given kind (from workout_entries table)
- For each workout date, collect the delta vs pre-workout baseline for
  HRV, RHR, and readiness at days +1 through +5
- Aggregate into median trajectory (day → {metric → median_delta})
- Assess where the user currently sits on the curve
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import sqrt
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric

try:
    from lattice.models import WorkoutEntry
    _HAS_WORKOUT_MODEL = True
except ImportError:
    _HAS_WORKOUT_MODEL = False

_RECOVERY_METRICS = ["hrv_overnight_avg", "resting_hr", "readiness_score"]
_RECOVERY_DAYS = 5
_MIN_WORKOUTS = 4


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


async def _get_metric_by_date(
    session: AsyncSession,
    metric_name: str,
    date_iso: str,
    zone: Any,
) -> float | None:
    stmt = select(Metric).where(
        Metric.metric_name == metric_name,
        Metric.timestamp >= f"{date_iso}T00:00:00",
        Metric.timestamp <= f"{date_iso}T23:59:59",
    ).order_by(Metric.timestamp.desc()).limit(1)
    row = (await session.execute(stmt)).scalar_one_or_none()
    return float(row.value) if row else None


async def compute_recovery_trajectory(
    session: AsyncSession,
    *,
    activity_kind: str,
    lookback_days: int = 180,
) -> dict[str, Any]:
    """Compute the personal recovery fingerprint after a given activity type.

    Returns:
      activity_kind        kind of workout analysed
      n_workouts           number of matching workouts found
      fingerprint          {metric: {day_1..5: median_delta}} vs pre-workout baseline
      days_to_full_recovery estimated days until metrics return to baseline
      recent_deviation     whether the last workout's recovery matches the fingerprint
      interpretation       human-readable summary
      low_confidence       true when n_workouts < MIN_WORKOUTS
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    start = today - timedelta(days=lookback_days - 1)

    # Fetch workouts — fall back to scanning workout_manual entries if no WorkoutEntry model
    workout_dates: list[date] = []

    if _HAS_WORKOUT_MODEL:
        try:
            stmt = select(WorkoutEntry).where(
                WorkoutEntry.kind == activity_kind,
                WorkoutEntry.started_at >= start.isoformat(),
            ).order_by(WorkoutEntry.started_at.asc())
            rows = list((await session.execute(stmt)).scalars().all())
            for r in rows:
                try:
                    d = datetime.fromisoformat(r.started_at).astimezone(zone).date()
                    workout_dates.append(d)
                except (ValueError, TypeError):
                    pass
        except Exception:
            pass

    # If no results from WorkoutEntry, try Entry with type=workout_manual
    if not workout_dates:
        from lattice.models import Entry
        import json

        stmt2 = select(Entry).where(
            Entry.type == "workout_manual",
            Entry.timestamp >= start.isoformat(),
        ).order_by(Entry.timestamp.asc())
        rows2 = list((await session.execute(stmt2)).scalars().all())
        for r in rows2:
            try:
                data = json.loads(r.data)
                kind = (data.get("activity_type") or data.get("kind") or "").lower()
                if activity_kind.lower() in kind or kind in activity_kind.lower():
                    d = datetime.fromisoformat(r.timestamp).astimezone(zone).date()
                    workout_dates.append(d)
            except Exception:
                pass

    # Also try metric: training_effect or aerobic_training_effect as proxy for 'had workout'
    if not workout_dates:
        stmt3 = select(Metric).where(
            Metric.metric_name.in_(["aerobic_training_effect", "anaerobic_training_effect"]),
            Metric.timestamp >= start.isoformat(),
            Metric.value > 1.0,
        ).order_by(Metric.timestamp.asc())
        rows3 = list((await session.execute(stmt3)).scalars().all())
        for r in rows3:
            try:
                d = datetime.fromisoformat(r.timestamp).astimezone(zone).date()
                if d not in workout_dates:
                    workout_dates.append(d)
            except (ValueError, TypeError):
                pass

    if len(workout_dates) < _MIN_WORKOUTS:
        return {
            "activity_kind": activity_kind,
            "n_workouts": len(workout_dates),
            "fingerprint": {},
            "days_to_full_recovery": None,
            "recent_deviation": None,
            "interpretation": (
                f"insufficient workout data for '{activity_kind}' "
                f"({len(workout_dates)} found, need ≥{_MIN_WORKOUTS})"
            ),
            "low_confidence": True,
        }

    # For each workout, compute day-by-day metric deltas for +1..+5 days
    # Baseline = the day of the workout (day 0 value)
    trajectories: dict[str, dict[int, list[float]]] = {
        m: {d: [] for d in range(1, _RECOVERY_DAYS + 1)} for m in _RECOVERY_METRICS
    }

    for wo_date in workout_dates:
        baselines: dict[str, float | None] = {}
        for m in _RECOVERY_METRICS:
            baselines[m] = await _get_metric_by_date(session, m, wo_date.isoformat(), zone)

        for delta_d in range(1, _RECOVERY_DAYS + 1):
            target_date = (wo_date + timedelta(days=delta_d)).isoformat()
            for m in _RECOVERY_METRICS:
                base = baselines[m]
                if base is None or base == 0:
                    continue
                val = await _get_metric_by_date(session, m, target_date, zone)
                if val is None:
                    continue
                trajectories[m][delta_d].append(val - base)

    # Build fingerprint (median deltas)
    fingerprint: dict[str, dict[str, float | None]] = {}
    for m in _RECOVERY_METRICS:
        fingerprint[m] = {}
        for d in range(1, _RECOVERY_DAYS + 1):
            med = _median(trajectories[m][d])
            fingerprint[m][f"day_{d}"] = round(med, 2) if med is not None else None

    # Estimate days to full recovery: first day where HRV delta >= 0 consistently
    days_to_recovery: int | None = None
    hrv_fp = fingerprint.get("hrv_overnight_avg", {})
    for d in range(1, _RECOVERY_DAYS + 1):
        v = hrv_fp.get(f"day_{d}")
        if v is not None and v >= 0:
            days_to_recovery = d
            break

    # Check recent workout recovery deviation
    recent_deviation: dict[str, Any] | None = None
    if workout_dates:
        last_wo = max(workout_dates)
        days_since = (today - last_wo).days
        if 1 <= days_since <= _RECOVERY_DAYS:
            deviations: list[str] = []
            for m in _RECOVERY_METRICS:
                expected = fingerprint[m].get(f"day_{days_since}")
                actual_val = await _get_metric_by_date(session, m, today.isoformat(), zone)
                base_val = await _get_metric_by_date(session, m, last_wo.isoformat(), zone)
                if expected is None or actual_val is None or base_val is None or base_val == 0:
                    continue
                actual_delta = actual_val - base_val
                diff = actual_delta - expected
                # Flag if deviation > 2x the fingerprint magnitude
                mag = abs(expected) or 1.0
                if abs(diff) > mag:
                    direction = "better" if (
                        (m == "hrv_overnight_avg" and diff > 0) or
                        (m == "resting_hr" and diff < 0) or
                        (m == "readiness_score" and diff > 0)
                    ) else "worse"
                    deviations.append(f"{m} recovering {direction} than typical (Δ={actual_delta:+.1f} vs expected {expected:+.1f})")

            recent_deviation = {
                "last_workout_date": last_wo.isoformat(),
                "days_since_workout": days_since,
                "deviations": deviations,
            }

    if days_to_recovery:
        interp = (
            f"Typical recovery after {activity_kind}: HRV returns to baseline in ~{days_to_recovery} day(s). "
        )
    else:
        interp = f"Recovery trajectory for {activity_kind}: "

    hrv_d1 = fingerprint.get("hrv_overnight_avg", {}).get("day_1")
    if hrv_d1 is not None:
        interp += f"HRV drops {hrv_d1:+.1f}ms on day+1. "

    if recent_deviation and recent_deviation["deviations"]:
        interp += "Current recovery: " + "; ".join(recent_deviation["deviations"]) + "."
    elif recent_deviation:
        interp += f"Current recovery (day+{recent_deviation['days_since_workout']}) is on track."

    return {
        "activity_kind": activity_kind,
        "n_workouts": len(workout_dates),
        "fingerprint": fingerprint,
        "days_to_full_recovery": days_to_recovery,
        "recent_deviation": recent_deviation,
        "interpretation": interp.strip(),
        "low_confidence": len(workout_dates) < 8,
    }


__all__ = ["compute_recovery_trajectory"]
