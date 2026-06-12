"""Read/write the single source of truth for sleep recommendations (Phase A).

The pain this resolves: every surface already calls F4, but the chat agent
reasons *past* F4 (weighing calendar, what the user said) while the website and
the evening brief print raw F4 — so they disagree. The fix is to persist the
AI's decision and have all surfaces read it.

Core invariant (unit-tested): a `formula` seed NEVER overwrites an existing
`ai` row. The getter is read-first — it only materializes/refreshes a formula
seed when there is no AI decision for the target date.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import parse_iso
from lattice.functions.sleep_window import compute_sleep_window
from lattice.models import Recommendation
from lattice.schemas.recommendation import SleepRecommendation

SLEEP_KIND = "sleep"


def tonight_target_date(tz: str) -> date:
    """The date you go to sleep ON tonight — F4's `target` parameter.

    Centralized so the sleep_window endpoint, caffeine math, and the evening
    brief never read different rows. Date-semantics drift is the main risk in
    Phase A: if one surface used `target` and another `target+1`, they would
    silently read separate recommendation rows.
    """
    return datetime.now(ZoneInfo(tz)).date()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _f4_rationale(f4_flags: list[str], wake_derivation: str | None) -> str:
    """A short deterministic rationale for a formula seed so the website/brief
    have something to show next to a `formula` badge."""
    parts: list[str] = []
    if wake_derivation:
        parts.append(f"Wake: {wake_derivation}.")
    if f4_flags:
        parts.append("Flags: " + "; ".join(f4_flags) + ".")
    return " ".join(parts) or "Derived from F4 sleep-window formula."


def _sleep_rec_from_row(
    row: Recommendation, *, flags: list[str] | None = None,
    inputs: dict[str, str | float | int | None] | None = None,
) -> SleepRecommendation:
    value = json.loads(row.value)
    return SleepRecommendation(
        date=row.target_date,
        bedtime=value["bedtime"],
        wake_time=value["wake_time"],
        target_duration_min=float(value["target_duration_min"]),
        flags=flags or [],
        inputs=inputs or {},
        source=row.source,
        rationale=row.rationale,
        author=row.author,
    )


async def _get_row(
    session: AsyncSession, kind: str, target_str: str,
) -> Recommendation | None:
    return (
        await session.execute(
            select(Recommendation).where(
                Recommendation.kind == kind,
                Recommendation.target_date == target_str,
            )
        )
    ).scalar_one_or_none()


async def get_active_sleep_recommendation(
    session: AsyncSession, *, target: date, tz: str,
) -> SleepRecommendation:
    """Return the authoritative sleep recommendation for `target`.

    If the AI has written a decision for this date, return it verbatim (never
    recompute, never overwrite). Otherwise compute F4 live and lazily seed/refresh
    a `formula` row, returning it with F4's flags + inputs attached.
    """
    target_str = target.isoformat()
    existing = await _get_row(session, SLEEP_KIND, target_str)
    if existing is not None and existing.source == "ai":
        return _sleep_rec_from_row(existing)

    # No AI decision — compute F4 live and (re)seed a formula row.
    f4 = await compute_sleep_window(session, target=target, tz=tz)
    value = {
        "bedtime": f4.bedtime,
        "wake_time": f4.wake_time,
        "target_duration_min": f4.target_duration_min,
    }
    rationale = _f4_rationale(f4.flags, f4.inputs.get("wake_derivation"))  # type: ignore[arg-type]

    if existing is None:
        row = Recommendation(
            kind=SLEEP_KIND,
            target_date=target_str,
            value=json.dumps(value),
            rationale=rationale,
            source="formula",
            author="f4_seed",
            created_at=_now_iso(),
        )
        session.add(row)
    else:
        # existing is a formula row (ai handled above) — refresh from live F4
        # so calendar/caffeine changes during the day stay reflected.
        existing.value = json.dumps(value)
        existing.rationale = rationale
        existing.created_at = _now_iso()
        row = existing
    await session.commit()
    await session.refresh(row)
    return _sleep_rec_from_row(row, flags=f4.flags, inputs=f4.inputs)


def _normalize_clock(value: str, *, target: date, tz: str, is_wake: bool) -> str:
    """Normalize an AI-supplied time to ISO 8601 with TZ offset on F4's dates.

    Accepts:
      - full ISO 8601 (with or without offset) → returned in `tz`
      - 'YYYY-MM-DDTHH:MM[:SS]' naive → tz attached
      - 'HH:MM' → date attached: wake → target+1 (morning); bedtime → target
        evening, or target+1 if it's an after-midnight time (hour < 12).
    """
    zone = ZoneInfo(tz)
    raw = value.strip()
    # Full ISO with a date component.
    if "T" in raw or len(raw) > 5:
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zone)
            return dt.astimezone(zone).isoformat()
        except ValueError:
            pass
    # Bare HH:MM.
    h, m = raw.split(":", 1)
    hour, minute = int(h), int(m)
    if is_wake:
        day = target + timedelta(days=1)
    else:
        # Evening bedtime stays on target; after-midnight rolls to target+1.
        day = target + timedelta(days=1) if hour < 12 else target
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=zone).isoformat()


async def set_sleep_recommendation(
    session: AsyncSession,
    *,
    target: date,
    tz: str,
    bedtime: str,
    wake_time: str,
    target_duration_min: float | None,
    rationale: str | None,
    author: str = "chat",
) -> SleepRecommendation:
    """Persist the AI's sleep decision for `target`. Always wins the slot."""
    bedtime_iso = _normalize_clock(bedtime, target=target, tz=tz, is_wake=False)
    wake_iso = _normalize_clock(wake_time, target=target, tz=tz, is_wake=True)
    if target_duration_min is None:
        bt = parse_iso(bedtime_iso)
        wt = parse_iso(wake_iso)
        target_duration_min = max(0.0, (wt - bt).total_seconds() / 60.0)
    value = {
        "bedtime": bedtime_iso,
        "wake_time": wake_iso,
        "target_duration_min": float(target_duration_min),
    }
    target_str = target.isoformat()
    existing = await _get_row(session, SLEEP_KIND, target_str)
    if existing is None:
        row = Recommendation(
            kind=SLEEP_KIND,
            target_date=target_str,
            value=json.dumps(value),
            rationale=rationale,
            source="ai",
            author=author,
            created_at=_now_iso(),
        )
        session.add(row)
    else:
        existing.value = json.dumps(value)
        existing.rationale = rationale
        existing.source = "ai"
        existing.author = author
        existing.created_at = _now_iso()
        row = existing
    await session.commit()
    await session.refresh(row)
    return _sleep_rec_from_row(row)


async def clear_sleep_recommendation(
    session: AsyncSession, *, target: date,
) -> None:
    """Delete any stored sleep recommendation (AI or formula) for `target`.

    Powers the "use algorithm" action: after deletion the getter re-seeds a
    fresh F4 formula row, so every surface falls back to the deterministic
    window instead of the AI's decision.
    """
    existing = await _get_row(session, SLEEP_KIND, target.isoformat())
    if existing is not None:
        await session.delete(existing)
        await session.commit()


__all__ = [
    "SLEEP_KIND",
    "clear_sleep_recommendation",
    "get_active_sleep_recommendation",
    "set_sleep_recommendation",
    "tonight_target_date",
]
