"""AI-writable personalized health targets (V — versatility rework).

Mirrors the `recommendation_store` pattern: stored, AI-owned values that
every surface reads, with a deterministic fallback derived from the user's
age + the static guidelines. The AI's decision always wins inside wide
medically-defensible outer guardrails; the static tables become a seed and a
safety net, not the law.

Stored kinds (all live in the `recommendations` table):
  - sleep_floor_min          (minutes — nightly sleep floor)
  - sleep_ceiling_min        (minutes — nightly sleep ceiling)
  - caffeine_daily_cap_mg    (mg — informative daily total cap)
  - caffeine_bedtime_residual_mg (mg — bedtime headroom; F5 uses)
  - caffeine_cutoff_hour     (local hour — F4 late-caffeine flag)

Rows are keyed by (kind, target_date) and we use a sentinel `target_date='*'`
for these "current global preference" values — there is no per-day axis.

Guardrails (clamped on write, surfaced in the rationale):
  - <18:  sleep floor ≥ 420 min (7 h), ceiling ≤ 660 min (11 h),
          daily caffeine cap ≤ 200 mg
  - adults: proportionally wider — floor ≥ 360 min (6 h),
            ceiling ≤ 720 min (12 h), daily cap ≤ 600 mg
  - both: bedtime residual ∈ [10, 100] mg; cutoff hour ∈ [8, 22]

These are *outer* safety bounds, not the answer; inside them the AI's
judgment wins. Clamping is logged + appended to the rationale so it shows
up wherever the target is displayed.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.sleep_window import (
    _age_on,
    _healthy_sleep_bounds_min,
)
from lattice.models import Profile, Recommendation

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Stored kinds (Recommendation.kind values).
SLEEP_FLOOR_KIND = "sleep_floor_min"
SLEEP_CEILING_KIND = "sleep_ceiling_min"
CAFFEINE_DAILY_CAP_KIND = "caffeine_daily_cap_mg"
CAFFEINE_BEDTIME_RESIDUAL_KIND = "caffeine_bedtime_residual_mg"
CAFFEINE_CUTOFF_HOUR_KIND = "caffeine_cutoff_hour"

ALL_KINDS: tuple[str, ...] = (
    SLEEP_FLOOR_KIND,
    SLEEP_CEILING_KIND,
    CAFFEINE_DAILY_CAP_KIND,
    CAFFEINE_BEDTIME_RESIDUAL_KIND,
    CAFFEINE_CUTOFF_HOUR_KIND,
)

# Sentinel target_date for global (non-per-day) targets.
GLOBAL_TARGET_DATE = "*"

# Static seed defaults — used only when the AI hasn't written anything and
# the table can't pin a value (e.g. caffeine cutoff hour).
DEFAULT_CAFFEINE_DAILY_CAP_ADULT_MG = 400.0
DEFAULT_CAFFEINE_DAILY_CAP_TEEN_MG = 100.0  # AAP guideline
DEFAULT_CAFFEINE_BEDTIME_RESIDUAL_MG = 50.0  # legacy F5 hard-coded constant
DEFAULT_CAFFEINE_CUTOFF_HOUR = 14


@dataclass(frozen=True)
class HealthTarget:
    kind: str
    value: float
    source: str  # 'ai' | 'default'
    rationale: str | None
    author: str | None


# --------------------------------------------------------------------------- #
# Outer guardrails
# --------------------------------------------------------------------------- #


def _is_minor(age: int | None) -> bool:
    return age is not None and age < 18


def outer_bounds(kind: str, age: int | None) -> tuple[float, float]:
    """Return (min, max) the AI is allowed to set for `kind` at this age.

    Wide enough that any reasonable expert call sits inside; tight enough
    that an LLM bad day can't persist a harmful target. Bounds are
    age-dependent for the two sleep kinds and the daily caffeine cap.
    """
    minor = _is_minor(age)
    if kind == SLEEP_FLOOR_KIND:
        return (420.0, 600.0) if minor else (360.0, 600.0)
    if kind == SLEEP_CEILING_KIND:
        return (480.0, 660.0) if minor else (420.0, 720.0)
    if kind == CAFFEINE_DAILY_CAP_KIND:
        return (0.0, 200.0) if minor else (0.0, 600.0)
    if kind == CAFFEINE_BEDTIME_RESIDUAL_KIND:
        return (10.0, 100.0)
    if kind == CAFFEINE_CUTOFF_HOUR_KIND:
        return (8.0, 22.0)
    raise ValueError(f"unknown health-target kind: {kind!r}")


def _clamp(value: float, lo: float, hi: float) -> tuple[float, bool]:
    """Clamp `value` to [lo, hi]; return (clamped, did_clamp)."""
    if value < lo:
        return lo, True
    if value > hi:
        return hi, True
    return value, False


# --------------------------------------------------------------------------- #
# Defaults / seeds
# --------------------------------------------------------------------------- #


def _seed_for(kind: str, age: int | None) -> float:
    """Deterministic fallback when no AI row exists for `kind`."""
    if kind == SLEEP_FLOOR_KIND:
        floor, _ = _healthy_sleep_bounds_min(age)
        return floor
    if kind == SLEEP_CEILING_KIND:
        _, ceil = _healthy_sleep_bounds_min(age)
        return ceil
    if kind == CAFFEINE_DAILY_CAP_KIND:
        return (
            DEFAULT_CAFFEINE_DAILY_CAP_TEEN_MG
            if _is_minor(age)
            else DEFAULT_CAFFEINE_DAILY_CAP_ADULT_MG
        )
    if kind == CAFFEINE_BEDTIME_RESIDUAL_KIND:
        return DEFAULT_CAFFEINE_BEDTIME_RESIDUAL_MG
    if kind == CAFFEINE_CUTOFF_HOUR_KIND:
        return float(DEFAULT_CAFFEINE_CUTOFF_HOUR)
    raise ValueError(f"unknown health-target kind: {kind!r}")


# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def _get_age(session: AsyncSession) -> int | None:
    profile = await session.get(Profile, 1)
    if profile is None:
        return None
    today = datetime.now(UTC).date()
    return _age_on(profile.birthday, today)


async def _get_row(session: AsyncSession, kind: str) -> Recommendation | None:
    return (
        await session.execute(
            select(Recommendation).where(
                Recommendation.kind == kind,
                Recommendation.target_date == GLOBAL_TARGET_DATE,
            )
        )
    ).scalar_one_or_none()


async def get_target(
    session: AsyncSession, kind: str, *, age: int | None = None,
) -> HealthTarget:
    """Return the active target for `kind`: AI row if present, else seed.

    `age` is read from Profile when not supplied. The store never auto-seeds
    on read (unlike sleep recommendations) — a `default` source is returned
    fresh each call so the AI can write a new value without touching the
    table first.
    """
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown health-target kind: {kind!r}")
    if age is None:
        age = await _get_age(session)
    row = await _get_row(session, kind)
    if row is not None and row.source == "ai":
        try:
            value = float(json.loads(row.value)["value"])
        except (KeyError, ValueError, TypeError):
            logger.warning("health_targets: corrupt AI row for %s — using seed", kind)
            value = _seed_for(kind, age)
            return HealthTarget(kind=kind, value=value, source="default",
                                rationale="corrupt stored row; using age-derived seed",
                                author=None)
        return HealthTarget(
            kind=kind, value=value, source="ai",
            rationale=row.rationale, author=row.author,
        )
    seed = _seed_for(kind, age)
    return HealthTarget(
        kind=kind, value=seed, source="default",
        rationale=f"age-derived default (age={age})",
        author=None,
    )


async def get_all_targets(
    session: AsyncSession,
) -> dict[str, HealthTarget]:
    """Return every active target keyed by `kind`. Convenient for surfaces."""
    age = await _get_age(session)
    return {k: await get_target(session, k, age=age) for k in ALL_KINDS}


# Public read helpers used by the deterministic functions. Each returns
# (value, source) so callers can surface provenance.


async def get_sleep_bounds_min(
    session: AsyncSession, *, age: int | None = None,
) -> tuple[float, float, str, str]:
    """Return (floor_min, ceiling_min, floor_source, ceiling_source).

    Used by F4 / sleep_debt instead of the static `_HEALTHY_BOUNDS_MIN` table.
    """
    if age is None:
        age = await _get_age(session)
    floor = await get_target(session, SLEEP_FLOOR_KIND, age=age)
    ceil = await get_target(session, SLEEP_CEILING_KIND, age=age)
    # Defensive: an AI write that violates floor < ceiling is repaired on read.
    floor_v = floor.value
    ceil_v = ceil.value
    if floor_v >= ceil_v:
        seed_floor, seed_ceil = _healthy_sleep_bounds_min(age)
        floor_v, ceil_v = seed_floor, seed_ceil
    return floor_v, ceil_v, floor.source, ceil.source


# --------------------------------------------------------------------------- #
# Write surface — used by the LLM tool + tests
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class HealthTargetWrite:
    kind: str
    value: float


@dataclass(frozen=True)
class HealthTargetWriteResult:
    kind: str
    requested: float
    stored: float
    clamped: bool
    bounds: tuple[float, float]
    source: str  # always 'ai' after a successful write
    rationale: str | None


async def set_health_targets(
    session: AsyncSession,
    *,
    writes: list[HealthTargetWrite],
    rationale: str | None,
    author: str = "chat",
) -> list[HealthTargetWriteResult]:
    """Persist one or more AI-set health targets.

    Each requested value is clamped into the per-kind outer guardrails for
    the user's age; clamping is appended to the rationale so the website /
    brief surfaces show "requested X, clamped to Y" without the caller
    needing to format anything. Multiple kinds in one call share the same
    rationale (the AI usually adjusts a coherent group).
    """
    if not writes:
        return []
    age = await _get_age(session)
    out: list[HealthTargetWriteResult] = []
    now = _now_iso()
    for w in writes:
        if w.kind not in ALL_KINDS:
            raise ValueError(f"unknown health-target kind: {w.kind!r}")
        lo, hi = outer_bounds(w.kind, age)
        clamped_value, did_clamp = _clamp(float(w.value), lo, hi)
        clamp_note = (
            f" (requested {w.value:g}, clamped to [{lo:g}, {hi:g}])"
            if did_clamp else ""
        )
        full_rationale = (rationale or "") + clamp_note
        full_rationale = full_rationale.strip() or None
        existing = await _get_row(session, w.kind)
        if existing is None:
            row = Recommendation(
                kind=w.kind,
                target_date=GLOBAL_TARGET_DATE,
                value=json.dumps({"value": clamped_value}),
                rationale=full_rationale,
                source="ai",
                author=author,
                created_at=now,
            )
            session.add(row)
        else:
            existing.value = json.dumps({"value": clamped_value})
            existing.rationale = full_rationale
            existing.source = "ai"
            existing.author = author
            existing.created_at = now
        out.append(HealthTargetWriteResult(
            kind=w.kind,
            requested=float(w.value),
            stored=clamped_value,
            clamped=did_clamp,
            bounds=(lo, hi),
            source="ai",
            rationale=full_rationale,
        ))
        if did_clamp:
            logger.info(
                "health_targets: %s clamped %s → %s (bounds [%s, %s])",
                w.kind, w.value, clamped_value, lo, hi,
            )
    await session.commit()
    return out


async def clear_target(session: AsyncSession, *, kind: str) -> None:
    """Remove any stored AI target for `kind`; getter falls back to seed."""
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown health-target kind: {kind!r}")
    row = await _get_row(session, kind)
    if row is not None:
        await session.delete(row)
        await session.commit()


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #


def target_to_dict(t: HealthTarget) -> dict[str, Any]:
    return {
        "kind": t.kind,
        "value": t.value,
        "source": t.source,
        "rationale": t.rationale,
        "author": t.author,
    }


__all__ = [
    "ALL_KINDS",
    "CAFFEINE_BEDTIME_RESIDUAL_KIND",
    "CAFFEINE_CUTOFF_HOUR_KIND",
    "CAFFEINE_DAILY_CAP_KIND",
    "GLOBAL_TARGET_DATE",
    "HealthTarget",
    "HealthTargetWrite",
    "HealthTargetWriteResult",
    "SLEEP_CEILING_KIND",
    "SLEEP_FLOOR_KIND",
    "clear_target",
    "get_all_targets",
    "get_sleep_bounds_min",
    "get_target",
    "outer_bounds",
    "set_health_targets",
    "target_to_dict",
]
