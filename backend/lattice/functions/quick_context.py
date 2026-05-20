"""`get_quick_context` — the chat agent's default first call.

Returns a compact 7-day snapshot so the LLM has cheap baseline context
before deciding whether to query deeper. Bundles: today's readiness,
recent sleep, last workout, 7-day medians for the headline metrics,
and habit adherence for the week.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.habits_adherence import compute_habit_adherence
from lattice.functions.readiness import compute_readiness
from lattice.functions.sleep_pattern import sleep_pattern
from lattice.functions.stats import stats_for_metric
from lattice.functions.workout_queries import last_workout

HEADLINE_DAILY_METRICS = [
    "hrv_overnight_avg",
    "resting_hr",
    "sleep_score",
    "sleep_duration_min",
    "body_battery_start",
    "stress_avg",
]


async def get_quick_context(session: AsyncSession) -> dict[str, Any]:
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    seven_days_back = today - timedelta(days=6)

    # Today's readiness — algorithm-grade.
    try:
        readiness = await compute_readiness(session, target=today, tz=settings.timezone)
        readiness_block = {
            "score": readiness.score,
            "category": readiness.category,
            "provisional": readiness.provisional,
        }
    except Exception:  # noqa: BLE001 — fail-soft
        readiness_block = {"score": None, "category": None, "provisional": True}

    # 7-day medians for headline metrics.
    medians: dict[str, Any] = {}
    for name in HEADLINE_DAILY_METRICS:
        s = await stats_for_metric(
            session, name,
            from_iso=seven_days_back.isoformat(),
            to_iso=today.isoformat(),
        )
        medians[name] = {
            "median": s["median"],
            "n": s["n"],
            "low_confidence": s["low_confidence"],
        }

    # Recent sleep pattern.
    sleep = await sleep_pattern(
        session,
        from_iso=seven_days_back.isoformat(),
        to_iso=today.isoformat(),
    )

    # Last workout, regardless of kind.
    lw = await last_workout(session)

    # Habit adherence for the past 7 days.
    try:
        adherence = await compute_habit_adherence(
            session,
            from_=seven_days_back,
            to=today,
            today=today,
        )
        habits_block: Any = adherence.model_dump() if hasattr(adherence, "model_dump") else adherence
    except Exception:  # noqa: BLE001 — fail-soft
        habits_block = {"habits": []}

    return {
        "window": {"from": seven_days_back.isoformat(), "to": today.isoformat()},
        "today": today.isoformat(),
        "readiness_today": readiness_block,
        "seven_day_medians": medians,
        "sleep_pattern": {
            "bedtime_median": sleep.get("bedtime_median"),
            "wake_median": sleep.get("wake_median"),
            "duration_median_min": sleep.get("duration_median_min"),
            "efficiency_median_pct": sleep.get("efficiency_median_pct"),
            "n_days": sleep.get("n_days"),
        },
        "last_workout": lw.get("workout"),
        "habits": habits_block,
        "note": (
            "This is the default 7-day context. For deeper analysis (single "
            "day, multi-month trends, intra-day hour windows), call the "
            "specific stats_* / workout_* / sleep_pattern tools with explicit "
            "from/to ranges."
        ),
    }
