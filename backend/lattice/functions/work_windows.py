"""F2 — Optimal Work Window (SPEC §6).

1. Find calendar gaps ≥ `min_minutes` between busy intervals on `target` day,
   bounded by reasonable wake/bedtime window (default 07:00–23:00 local).
2. Score each gap on 0–100:
   - 40%: time-of-day match to peak focus hour (mean hour of focus entries,
     weighted by focus.score, last 30 days)
   - 30%: today's readiness score (constant across gaps)
   - 20%: predicted Body Battery at gap midpoint (linear interp on today's
     bb start/min/end markers — coarse but no per-hour data in metrics)
   - 10%: meal/workout spacing penalty (≥30 min from any meal/workout)
3. Return top 3.

Peak focus hour fallback: 10:00 local with `confidence_hint=low` if no focus
entries exist in the last 30 days.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import metric_on_date, parse_iso
from lattice.models import CalendarCache, Entry
from lattice.schemas.functions import WorkWindow, WorkWindowsOutput

DAY_START_HOUR = 7
DAY_END_HOUR = 23
DEFAULT_PEAK_HOUR = 10
SPACING_MINUTES = 30


async def _busy_intervals(
    session: AsyncSession, target: date, tz: str,
) -> list[tuple[datetime, datetime]]:
    """All timed calendar events overlapping `target` day in `tz`."""
    zone = ZoneInfo(tz)
    day_start = datetime.combine(target, time(hour=DAY_START_HOUR), tzinfo=zone)
    day_end = datetime.combine(target, time(hour=DAY_END_HOUR), tzinfo=zone)

    stmt = (
        select(CalendarCache)
        .where(
            CalendarCache.is_all_day == 0,
            CalendarCache.end >= day_start.isoformat(),
            CalendarCache.start <= day_end.isoformat(),
        )
    )
    out: list[tuple[datetime, datetime]] = []
    for row in (await session.execute(stmt)).scalars().all():
        try:
            s = parse_iso(row.start).astimezone(zone)
            e = parse_iso(row.end).astimezone(zone)
        except ValueError:
            continue
        s = max(s, day_start)
        e = min(e, day_end)
        if e > s:
            out.append((s, e))
    out.sort()
    return out


def _find_gaps(
    busy: list[tuple[datetime, datetime]],
    day_start: datetime,
    day_end: datetime,
    min_minutes: int,
) -> list[tuple[datetime, datetime]]:
    """Compute the inverse of `busy` within [day_start, day_end]."""
    gaps: list[tuple[datetime, datetime]] = []
    cursor = day_start
    for s, e in busy:
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if day_end > cursor:
        gaps.append((cursor, day_end))
    return [
        (s, e) for s, e in gaps
        if (e - s) >= timedelta(minutes=min_minutes)
    ]


async def _peak_focus_hour(
    session: AsyncSession, target: date, tz: str,
) -> tuple[int | None, int]:
    """Returns (peak_hour or None, n_entries)."""
    zone = ZoneInfo(tz)
    start = datetime.combine(target - timedelta(days=30), time.min, tzinfo=zone)
    stmt = (
        select(Entry)
        .where(Entry.type == "focus", Entry.timestamp >= start.isoformat())
    )
    rows = (await session.execute(stmt)).scalars().all()
    weighted_sum = 0.0
    weight_total = 0.0
    n = 0
    for row in rows:
        try:
            data = json.loads(row.data)
            score = float(data.get("score", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
        if score <= 0:
            continue
        try:
            hour = parse_iso(row.timestamp).astimezone(zone).hour
        except ValueError:
            continue
        weighted_sum += score * hour
        weight_total += score
        n += 1
    if weight_total == 0:
        return None, 0
    return int(round(weighted_sum / weight_total)) % 24, n


def _time_of_day_score(midpoint_hour: float, peak_hour: int) -> float:
    """Triangular falloff: 1.0 at peak, 0.0 at ±6h. Wraps around midnight."""
    diff = abs(midpoint_hour - peak_hour)
    diff = min(diff, 24 - diff)
    return max(0.0, 1.0 - diff / 6.0)


def _bb_at_hour(
    hour: float,
    bb_start: float | None,
    bb_min: float | None,
    bb_end: float | None,
) -> float:
    """Linear interp across (start at ~08:00) → (min at ~14:00) → (end at ~22:00).

    Returns 0.5 if no markers exist (neutral). The exact hours are coarse —
    SPEC mentions the "Body Battery curve" without prescribing keypoints.
    """
    if bb_start is None and bb_min is None and bb_end is None:
        return 0.5
    points = []
    if bb_start is not None:
        points.append((8.0, bb_start / 100.0))
    if bb_min is not None:
        points.append((14.0, bb_min / 100.0))
    if bb_end is not None:
        points.append((22.0, bb_end / 100.0))
    if len(points) == 1:
        return points[0][1]
    points.sort()
    # Clamp to ends.
    if hour <= points[0][0]:
        return points[0][1]
    if hour >= points[-1][0]:
        return points[-1][1]
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h0 <= hour <= h1:
            frac = (hour - h0) / (h1 - h0)
            return v0 + frac * (v1 - v0)
    return 0.5


async def _meal_workout_times(
    session: AsyncSession, target: date, tz: str,
) -> list[datetime]:
    zone = ZoneInfo(tz)
    start = datetime.combine(target, time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    stmt = (
        select(Entry)
        .where(
            Entry.type.in_(["food", "workout_manual"]),
            Entry.timestamp >= start.isoformat(),
            Entry.timestamp < end.isoformat(),
        )
    )
    out: list[datetime] = []
    for row in (await session.execute(stmt)).scalars().all():
        try:
            out.append(parse_iso(row.timestamp).astimezone(zone))
        except ValueError:
            continue
    return out


def _spacing_score(midpoint: datetime, anchors: list[datetime]) -> float:
    """1.0 if all anchors are ≥SPACING_MINUTES away from midpoint; 0.0 otherwise."""
    if not anchors:
        return 1.0
    closest = min(abs((midpoint - a).total_seconds()) for a in anchors)
    return 1.0 if closest >= SPACING_MINUTES * 60 else 0.0


async def compute_work_windows(
    session: AsyncSession,
    *,
    target: date,
    tz: str,
    min_minutes: int,
    readiness_score: float | None,
) -> WorkWindowsOutput:
    zone = ZoneInfo(tz)
    day_start = datetime.combine(target, time(hour=DAY_START_HOUR), tzinfo=zone)
    day_end = datetime.combine(target, time(hour=DAY_END_HOUR), tzinfo=zone)

    busy = await _busy_intervals(session, target, tz)
    gaps = _find_gaps(busy, day_start, day_end, min_minutes)
    peak_hour, n_focus = await _peak_focus_hour(session, target, tz)
    confidence = "high" if n_focus >= 10 else "medium" if n_focus >= 3 else "low"
    effective_peak = peak_hour if peak_hour is not None else DEFAULT_PEAK_HOUR

    bb_start = await metric_on_date(session, "body_battery_start", target, tz)
    bb_min = await metric_on_date(session, "body_battery_min", target, tz)
    bb_end = await metric_on_date(session, "body_battery_end", target, tz)
    anchors = await _meal_workout_times(session, target, tz)

    readiness_unit = (readiness_score / 100.0) if readiness_score is not None else 0.5

    windows: list[WorkWindow] = []
    for s, e in gaps:
        midpoint = s + (e - s) / 2
        midpoint_hour = midpoint.hour + midpoint.minute / 60.0
        tod = _time_of_day_score(midpoint_hour, effective_peak)
        bb = _bb_at_hour(
            midpoint_hour,
            bb_start.value if bb_start else None,
            bb_min.value if bb_min else None,
            bb_end.value if bb_end else None,
        )
        spacing = _spacing_score(midpoint, anchors)
        scaled = 0.40 * tod + 0.30 * readiness_unit + 0.20 * bb + 0.10 * spacing
        predicted_focus = round(scaled * 100)

        rationale = [
            f"midpoint {midpoint.strftime('%H:%M')} vs peak hour {effective_peak:02d}:00",
            f"readiness {int(readiness_score) if readiness_score is not None else 'unknown'}",
            f"body battery predicted ~{int(bb * 100)} at midpoint",
        ]
        if spacing < 1.0:
            rationale.append(f"meal/workout within {SPACING_MINUTES}min — penalty")
        windows.append(
            WorkWindow(
                start=s.isoformat(),
                end=e.isoformat(),
                duration_minutes=(e - s).total_seconds() / 60.0,
                predicted_focus=predicted_focus,
                rationale=rationale,
            )
        )

    windows.sort(key=lambda w: w.predicted_focus, reverse=True)
    return WorkWindowsOutput(
        date=target.isoformat(),
        min_minutes=min_minutes,
        windows=windows[:3],
        peak_focus_hour=peak_hour,
        confidence_hint=confidence,
    )


__all__ = ["compute_work_windows"]
