"""F1 — Daily Readiness Score (SPEC §6).

Pure: takes a session + target date + tz, returns ReadinessOutput.

Algorithm (SPEC §6 F1):
  hrv_z   = clamp((hrv_today − mean_hrv_14d) / sd_hrv_14d, -2, +2)
  rhr_z   = clamp(-(rhr_today − mean_rhr_14d) / sd_rhr_14d, -2, +2)   ← negated
  → map z → 0-1 via (z + 2) / 4
  sleep_c = sleep_score / 100
  bb_c    = body_battery_start / 100
  stress_c = 1 − stress_yesterday / 100
  raw     = 0.40·hrv + 0.30·sleep_c + 0.15·rhr + 0.10·bb_c + 0.05·stress_c
  score   = round(raw · 100)

Missing data: drop the component and renormalize remaining weights to sum to 1.
<7d of either HRV or RHR baseline → provisional=true (but still scored).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import (
    clamp,
    compute_baseline,
    metric_on_date,
)
from lattice.schemas.functions import (
    ReadinessCategory,
    ReadinessExplanation,
    ReadinessOutput,
)

WEIGHTS: dict[str, float] = {
    "hrv": 0.40,
    "sleep": 0.30,
    "rhr": 0.15,
    "bb": 0.10,
    "stress": 0.05,
}

PROVISIONAL_THRESHOLD_DAYS = 7


def _z_to_unit(z: float) -> float:
    """Map clamped z-score in [-2, +2] onto [0, 1]."""
    return (z + 2.0) / 4.0


def _categorize(score: int) -> ReadinessCategory:
    if score >= 80:
        return "peak"
    if score >= 65:
        return "solid"
    if score >= 50:
        return "average"
    if score >= 35:
        return "low"
    return "depleted"


async def compute_readiness(
    session: AsyncSession, *, target: date, tz: str,
) -> ReadinessOutput:
    """Compute F1 for `target` date in `tz` (the user's local timezone)."""
    # 1. Today's metrics (anchored at midnight of `target`).
    hrv_row = await metric_on_date(session, "hrv_overnight_avg", target, tz)
    sleep_row = await metric_on_date(session, "sleep_score", target, tz)
    rhr_row = await metric_on_date(session, "resting_hr", target, tz)
    bb_row = await metric_on_date(session, "body_battery_start", target, tz)
    # Yesterday's stress (SPEC: stress_yesterday).
    yesterday = target - timedelta(days=1)
    stress_row = await metric_on_date(session, "stress_avg", yesterday, tz)

    # 2. Baselines. Exclude `target` so today's HRV/RHR isn't compared against
    # itself — the SPEC's "14-day baseline" means trailing-14, not inclusive.
    hrv_baseline = await compute_baseline(
        session, "hrv_overnight_avg", days=14, before=target, tz=tz,
    )
    rhr_baseline = await compute_baseline(
        session, "resting_hr", days=14, before=target, tz=tz,
    )

    components: dict[str, float] = {}
    missing: list[str] = []
    notes: list[str] = []

    # HRV component (z → unit interval)
    if hrv_row is not None and hrv_baseline.mean is not None and hrv_baseline.sd:
        z = clamp(
            (hrv_row.value - hrv_baseline.mean) / hrv_baseline.sd, -2.0, +2.0,
        )
        components["hrv"] = _z_to_unit(z)
    else:
        missing.append("hrv")
        if hrv_baseline.n < 2:
            notes.append("hrv baseline insufficient (need ≥2 days)")

    # Sleep component
    if sleep_row is not None:
        components["sleep"] = clamp(sleep_row.value / 100.0, 0.0, 1.0)
    else:
        missing.append("sleep_score")

    # RHR component (z is NEGATED: lower RHR is better)
    if rhr_row is not None and rhr_baseline.mean is not None and rhr_baseline.sd:
        z = clamp(
            -(rhr_row.value - rhr_baseline.mean) / rhr_baseline.sd, -2.0, +2.0,
        )
        components["rhr"] = _z_to_unit(z)
    else:
        missing.append("resting_hr")
        if rhr_baseline.n < 2:
            notes.append("rhr baseline insufficient (need ≥2 days)")

    # Body Battery start component
    if bb_row is not None:
        components["bb"] = clamp(bb_row.value / 100.0, 0.0, 1.0)
    else:
        missing.append("body_battery_start")

    # Stress (yesterday) — note: lower stress is better, so invert
    if stress_row is not None:
        components["stress"] = clamp(1.0 - (stress_row.value / 100.0), 0.0, 1.0)
    else:
        missing.append("stress_avg")

    # 3. Renormalize available weights to sum to 1.
    available_weights = {k: WEIGHTS[k] for k in components}
    total_weight = sum(available_weights.values())
    if total_weight == 0:
        # No data at all — return 0 with all components missing.
        return ReadinessOutput(
            date=target.isoformat(),
            score=0,
            category="depleted",
            provisional=True,
            explanation=ReadinessExplanation(
                weights_used={},
                missing=missing,
                components={},
                notes=["no data available"] + notes,
            ),
        )

    renormalized = {k: w / total_weight for k, w in available_weights.items()}
    raw = sum(renormalized[k] * components[k] for k in components)
    score = round(raw * 100)
    score = max(0, min(100, score))

    provisional = (
        hrv_baseline.n < PROVISIONAL_THRESHOLD_DAYS
        or rhr_baseline.n < PROVISIONAL_THRESHOLD_DAYS
    )
    if provisional:
        notes.append(
            f"provisional: hrv n={hrv_baseline.n}, rhr n={rhr_baseline.n} "
            f"(<{PROVISIONAL_THRESHOLD_DAYS}d baseline)"
        )

    return ReadinessOutput(
        date=target.isoformat(),
        score=score,
        category=_categorize(score),
        provisional=provisional,
        explanation=ReadinessExplanation(
            weights_used=renormalized,
            missing=missing,
            components=components,
            notes=notes,
        ),
    )


__all__ = ["WEIGHTS", "compute_readiness"]
