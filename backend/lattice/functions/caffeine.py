"""F5 — Caffeine Cutoff Advisor (SPEC §6).

Half-life model: dose · 0.5^(hours / 5h). Default 80mg per cup.

  - existing_residual_at_bedtime = sum over today's coffee entries
  - safe_for_new_cup = (existing + 80 · 0.5^(hours_to_bed/5)) ≤ 50mg
  - last_call_minutes: largest minute offset from `at` such that adding a cup
    that many minutes from now would still keep residual ≤ 50mg.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import parse_iso
from lattice.functions.sleep_window import compute_sleep_window
from lattice.models import Entry
from lattice.schemas.functions import CaffeineStatusOutput

HALF_LIFE_HOURS = 5.0
DEFAULT_DOSE_MG = 80.0
MAX_BEDTIME_RESIDUAL_MG = 50.0


def _residual(dose_mg: float, hours_until: float) -> float:
    if hours_until <= 0:
        return dose_mg
    return dose_mg * (0.5 ** (hours_until / HALF_LIFE_HOURS))


async def _today_caffeine(
    session: AsyncSession, target: date, tz: str,
) -> list[tuple[datetime, float]]:
    """Return (timestamp, dose_mg) tuples for today's caffeine entries."""
    zone = ZoneInfo(tz)
    day_start = datetime.combine(target, time.min, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Entry)
        .where(
            Entry.type == "drink",
            Entry.timestamp >= day_start.isoformat(),
            Entry.timestamp < day_end.isoformat(),
        )
    )
    out: list[tuple[datetime, float]] = []
    for row in (await session.execute(stmt)).scalars().all():
        try:
            data = json.loads(row.data)
        except json.JSONDecodeError:
            continue
        caffeine_mg = data.get("caffeine_mg")
        kind = data.get("kind", "")
        count = float(data.get("count") or 1)
        if caffeine_mg is not None and float(caffeine_mg) > 0:
            dose = float(caffeine_mg) * count
        elif kind == "coffee":
            # Legacy entries that pre-date the caffeine_mg field
            dose = DEFAULT_DOSE_MG * count
        else:
            continue  # not caffeinated
        try:
            ts = parse_iso(row.timestamp).astimezone(zone)
        except ValueError:
            continue
        out.append((ts, dose))
    return out


async def compute_caffeine_status(
    session: AsyncSession,
    *,
    at: datetime,
    tz: str,
    bedtime_override: datetime | None = None,
) -> CaffeineStatusOutput:
    """Compute F5 for the instant `at`.

    If `bedtime_override` is None, F4 is called to determine bedtime.
    """
    zone = ZoneInfo(tz)
    at = at.astimezone(zone)
    target = at.date()

    if bedtime_override is not None:
        bedtime = bedtime_override.astimezone(zone)
    else:
        sleep = await compute_sleep_window(session, target=target, tz=tz)
        bedtime = parse_iso(sleep.bedtime).astimezone(zone)

    cups = await _today_caffeine(session, target, tz)

    existing_residual = 0.0
    for ts, dose in cups:
        hours = (bedtime - ts).total_seconds() / 3600.0
        existing_residual += _residual(dose, hours)

    hours_now_to_bed = (bedtime - at).total_seconds() / 3600.0
    additional_if_now = _residual(DEFAULT_DOSE_MG, hours_now_to_bed)
    safe_for_new_cup = (existing_residual + additional_if_now) <= MAX_BEDTIME_RESIDUAL_MG

    # last_call: solve for hours such that residual(80, hours) ≤ remaining headroom.
    headroom = MAX_BEDTIME_RESIDUAL_MG - existing_residual
    if headroom <= 0:
        last_call_minutes = None  # No new cup is safe at all today.
    else:
        # residual = 80 * 0.5^(h/5) = headroom → h = 5 * log2(80/headroom)
        from math import log2
        ratio = DEFAULT_DOSE_MG / headroom
        h_required = HALF_LIFE_HOURS * log2(ratio) if ratio > 1 else 0.0
        # That's the MINIMUM hours before bed a cup needs to be taken.
        # last_call = bedtime − h_required.
        last_call_dt = bedtime - timedelta(hours=h_required)
        delta_min = int((last_call_dt - at).total_seconds() / 60)
        last_call_minutes = max(0, delta_min) if delta_min >= 0 else None

    return CaffeineStatusOutput(
        at=at.isoformat(),
        bedtime=bedtime.isoformat(),
        residual_at_bedtime_mg=round(existing_residual, 2),
        safe_for_new_cup=safe_for_new_cup,
        last_call_minutes=last_call_minutes,
        inputs={
            "cups_today": len(cups),
            "headroom_mg": round(max(headroom, 0), 2),
            "hours_to_bed": round(hours_now_to_bed, 2),
            "default_dose_mg": DEFAULT_DOSE_MG,
        },
    )


__all__ = ["compute_caffeine_status"]
