"""Sleep-pattern aggregators.

`sleep_pattern` — bedtime/wake/duration medians (uses daily aggregates).
`sleep_stages_for_night` — full stage timeline for a single night.
`sleep_stages_pattern` — multi-night aggregate of stage timing/cycling:
  median minutes per stage, when first deep/REM typically occurs relative
  to sleep onset, REM cycle count, wake-event count, longest deep block.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date as _date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.stats import _fetch_values, _normalize_from, _normalize_to
from lattice.models import SleepStage


def _minutes_to_hhmm(m: float | None) -> str | None:
    """1410 -> '23:30'; 30 -> '00:30'. Wraps at 1440 just in case."""
    if m is None:
        return None
    total = int(round(m)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _circular_median_min(values: list[float]) -> float | None:
    """Median of clock-time values (minutes-past-midnight) handling the
    midnight wraparound.

    For bedtimes that straddle midnight (e.g., one night 23:30, next 00:30),
    a plain median gives garbage. We map to unit-circle coordinates, take
    the mean direction, convert back.
    """
    if not values:
        return None
    import math
    sins = [math.sin(2 * math.pi * v / 1440.0) for v in values]
    coss = [math.cos(2 * math.pi * v / 1440.0) for v in values]
    msin = statistics.mean(sins)
    mcos = statistics.mean(coss)
    if msin == 0 and mcos == 0:
        return statistics.median(values)
    angle = math.atan2(msin, mcos)
    minutes = (angle / (2 * math.pi) * 1440.0) % 1440.0
    return minutes


async def sleep_pattern(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Median bedtime / wake time / duration / efficiency over the window."""
    f = _normalize_from(from_iso, default_days_back=14)
    t = _normalize_to(to_iso)

    starts = await _fetch_values(session, "sleep_start_time", f, t)
    ends = await _fetch_values(session, "sleep_end_time", f, t)
    durations = await _fetch_values(session, "sleep_duration_min", f, t)
    efficiencies = await _fetch_values(session, "sleep_efficiency", f, t)

    bedtime_min = _circular_median_min(starts)
    wake_min = _circular_median_min(ends)

    n = max(len(starts), len(ends), len(durations))
    return {
        "from": f,
        "to": t,
        "n_days": n,
        "low_confidence": n < 5,
        "bedtime_median": _minutes_to_hhmm(bedtime_min),
        "wake_median": _minutes_to_hhmm(wake_min),
        "bedtime_n": len(starts),
        "wake_n": len(ends),
        "duration_median_min": (
            round(statistics.median(durations), 1) if durations else None
        ),
        "duration_iqr_min": (
            [
                round(statistics.quantiles(durations, n=4, method="inclusive")[0], 1),
                round(statistics.quantiles(durations, n=4, method="inclusive")[2], 1),
            ]
            if len(durations) >= 4
            else None
        ),
        "efficiency_median_pct": (
            round(statistics.median(efficiencies), 1) if efficiencies else None
        ),
    }


# --------------------------------------------------------------------------- #
# Sleep stage timeline queries
# --------------------------------------------------------------------------- #

STAGES = ("awake", "light", "deep", "rem")


def _stage_to_dict(s: SleepStage) -> dict[str, Any]:
    return {
        "stage": s.stage,
        "start": s.start,
        "end": s.end,
        "duration_min": s.duration_min,
    }


async def sleep_stages_for_night(
    session: AsyncSession,
    night_date: str,
) -> dict[str, Any]:
    """Return the chronological stage timeline for one night.

    `night_date` is the WAKE date (YYYY-MM-DD). Each segment carries its
    start/end ISO timestamps, stage label, and duration. Also returns total
    minutes per stage + a count of wake events for quick reference.
    """
    stmt = (
        select(SleepStage)
        .where(SleepStage.night_date == night_date)
        .order_by(SleepStage.start.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    totals: dict[str, float] = {s: 0.0 for s in STAGES}
    for r in rows:
        if r.stage in totals:
            totals[r.stage] += r.duration_min
    wake_events = sum(1 for r in rows if r.stage == "awake")
    return {
        "night_date": night_date,
        "n_segments": len(rows),
        "totals_min": {s: round(totals[s], 1) for s in STAGES},
        "wake_events": wake_events,
        "segments": [_stage_to_dict(r) for r in rows],
    }


def _first_offset_min(
    segments: list[SleepStage], target_stage: str, sleep_start_iso: str,
) -> float | None:
    """Minutes from sleep onset to the first occurrence of `target_stage`."""
    try:
        onset = datetime.fromisoformat(sleep_start_iso)
    except ValueError:
        return None
    for s in segments:
        if s.stage != target_stage:
            continue
        try:
            dt = datetime.fromisoformat(s.start)
        except ValueError:
            continue
        delta = (dt - onset).total_seconds() / 60.0
        if delta < 0:
            continue
        return round(delta, 1)
    return None


def _longest_block_min(segments: list[SleepStage], stage: str) -> float | None:
    blocks = [s.duration_min for s in segments if s.stage == stage]
    return round(max(blocks), 1) if blocks else None


def _rem_cycle_count(segments: list[SleepStage]) -> int:
    """Count contiguous REM blocks (separated by non-REM stages)."""
    cycles = 0
    prev_was_rem = False
    for s in segments:
        if s.stage == "rem":
            if not prev_was_rem:
                cycles += 1
            prev_was_rem = True
        else:
            prev_was_rem = False
    return cycles


async def sleep_stages_pattern(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Multi-night aggregate of stage timing & cycling.

    For each stage:
      - median minutes per night
      - median first-appearance offset (minutes after sleep onset)
      - median longest contiguous block

    Plus across-night medians of:
      - REM cycle count
      - wake-event count
      - sleep efficiency
    """
    f = _normalize_from(from_iso, default_days_back=14)
    t = _normalize_to(to_iso)

    # Resolve nights from the date range using the wake-day key.
    f_day = f[:10]
    t_day = t[:10]

    stmt = (
        select(SleepStage)
        .where(SleepStage.night_date >= f_day)
        .where(SleepStage.night_date <= t_day)
        .order_by(SleepStage.night_date.asc(), SleepStage.start.asc())
    )
    all_rows = list((await session.execute(stmt)).scalars().all())

    by_night: dict[str, list[SleepStage]] = defaultdict(list)
    for r in all_rows:
        by_night[r.night_date].append(r)

    if not by_night:
        return {
            "from": f, "to": t,
            "n_nights": 0,
            "low_confidence": True,
            "note": "no sleep_stages rows in range — sync Garmin first or extend range",
        }

    totals_by_stage: dict[str, list[float]] = defaultdict(list)
    first_offsets: dict[str, list[float]] = defaultdict(list)
    longest_blocks: dict[str, list[float]] = defaultdict(list)
    rem_cycles: list[int] = []
    wake_counts: list[int] = []

    for _night, segs in by_night.items():
        # Sleep onset = start of the first non-awake segment.
        sleep_start: str | None = next(
            (s.start for s in segs if s.stage != "awake"), None,
        )
        per_night_totals: dict[str, float] = {s: 0.0 for s in STAGES}
        for s in segs:
            if s.stage in per_night_totals:
                per_night_totals[s.stage] += s.duration_min
        for stg in STAGES:
            totals_by_stage[stg].append(per_night_totals[stg])
            lb = _longest_block_min(segs, stg)
            if lb is not None:
                longest_blocks[stg].append(lb)
            if sleep_start:
                fo = _first_offset_min(segs, stg, sleep_start)
                if fo is not None:
                    first_offsets[stg].append(fo)
        rem_cycles.append(_rem_cycle_count(segs))
        wake_counts.append(sum(1 for s in segs if s.stage == "awake"))

    def _med(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 1) if xs else None

    def _med_int(xs: list[int]) -> float | None:
        return round(statistics.median(xs), 1) if xs else None

    n = len(by_night)
    stages_block = {}
    for stg in STAGES:
        stages_block[stg] = {
            "median_min": _med(totals_by_stage[stg]),
            "median_first_offset_min": _med(first_offsets[stg]),
            "median_longest_block_min": _med(longest_blocks[stg]),
            "n": len(totals_by_stage[stg]),
        }
    return {
        "from": f, "to": t,
        "n_nights": n,
        "low_confidence": n < 5,
        "stages": stages_block,
        "median_rem_cycles_per_night": _med_int(rem_cycles),
        "median_wake_events_per_night": _med_int(wake_counts),
    }
