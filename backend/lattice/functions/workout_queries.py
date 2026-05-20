"""Workout query helpers — reads from the `workouts` table (SPEC §4.8).

These power the LLM's `list_workouts`, `workout_stats`, and `last_workout`
tools. All pure functions; pass a session in.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.stats import _normalize_from, _normalize_to
from lattice.models import Workout

LIST_CAP = 50


def _workout_to_dict(w: Workout) -> dict[str, Any]:
    meta: dict[str, Any] | None = None
    if w.extra_metadata:
        try:
            meta = json.loads(w.extra_metadata)
        except (ValueError, TypeError):
            meta = None
    return {
        "id": w.id,
        "garmin_activity_id": w.garmin_activity_id,
        "start": w.start,
        "duration_min": w.duration_min,
        "kind": w.kind,
        "distance_m": w.distance_m,
        "avg_hr": w.avg_hr,
        "max_hr": w.max_hr,
        "calories": w.calories,
        "training_effect": w.training_effect,
        "metadata": meta,
    }


async def list_workouts(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Up to `LIST_CAP` workouts newest-first."""
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    stmt = (
        select(Workout)
        .where(Workout.start >= f)
        .where(Workout.start <= t)
        .order_by(Workout.start.desc())
        .limit(LIST_CAP)
    )
    if kind:
        stmt = stmt.where(Workout.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "from": f, "to": t, "kind": kind,
        "n": len(rows),
        "capped": len(rows) >= LIST_CAP,
        "workouts": [_workout_to_dict(w) for w in rows],
    }


def _median_or_none(vs: list[float]) -> float | None:
    return round(statistics.median(vs), 3) if vs else None


async def workout_stats(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Per-kind counts + median duration / distance / avg_hr / training_effect."""
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    stmt = (
        select(Workout)
        .where(Workout.start >= f)
        .where(Workout.start <= t)
    )
    if kind:
        stmt = stmt.where(Workout.kind == kind)
    rows = (await session.execute(stmt)).scalars().all()

    by_kind: dict[str, list[Workout]] = defaultdict(list)
    for w in rows:
        by_kind[w.kind].append(w)

    breakdown: dict[str, dict[str, Any]] = {}
    for k, ws in by_kind.items():
        durations = [w.duration_min for w in ws if w.duration_min is not None]
        distances = [w.distance_m for w in ws if w.distance_m is not None]
        avg_hrs = [w.avg_hr for w in ws if w.avg_hr is not None]
        tes = [w.training_effect for w in ws if w.training_effect is not None]
        breakdown[k] = {
            "count": len(ws),
            "median_duration_min": _median_or_none(durations),
            "median_distance_m": _median_or_none(distances),
            "median_avg_hr": _median_or_none(avg_hrs),
            "median_training_effect": _median_or_none(tes),
        }
    return {
        "from": f, "to": t, "kind": kind,
        "total": len(rows),
        "by_kind": breakdown,
    }


async def last_workout(
    session: AsyncSession,
    kind: str | None = None,
) -> dict[str, Any]:
    """Most recent workout (optionally filtered by kind), or `None`."""
    stmt = select(Workout).order_by(Workout.start.desc()).limit(1)
    if kind:
        stmt = stmt.where(Workout.kind == kind)
    w = (await session.execute(stmt)).scalar_one_or_none()
    return {"workout": _workout_to_dict(w) if w else None, "kind": kind}
