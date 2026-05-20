"""F4 — Sleep Window (SPEC §6).

Algorithm:
  wake = first_event_tomorrow − 30 min   (if no event tomorrow → 08:00 local)
  bedtime = wake − optimal_sleep_duration

  optimal_sleep_duration = median of sleep_duration_min on days where the
  NEXT day's readiness was ≥ 65, over the last 60 days. Fallback 7.5h
  (= 450 min) if <5 qualifying days.

Flags:
  - caffeine logged after 14:00 local on `target`
  - workout_manual with intensity=high within 3h of computed bedtime
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import metric_for_day_range, parse_iso
from lattice.models import CalendarCache, Entry, Profile
from lattice.schemas.functions import SleepWindowOutput

FALLBACK_DURATION_MIN = 450.0
LOOKBACK_DAYS = 60
MIN_QUALIFYING_DAYS = 5
READINESS_GOOD_THRESHOLD = 65
DEFAULT_WAKE_HOUR = 8
DEFAULT_CAFFEINE_CUTOFF_HOUR = 14
LATE_WORKOUT_WINDOW_H = 3


async def _first_event_tomorrow(
    session: AsyncSession, target: date, tz: str,
) -> datetime | None:
    """Earliest timed event on the day after `target` (in `tz`)."""
    zone = ZoneInfo(tz)
    tomorrow = target + timedelta(days=1)
    day_start = datetime.combine(tomorrow, time.min, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(CalendarCache)
        .where(
            CalendarCache.is_all_day == 0,
            CalendarCache.start >= day_start.isoformat(),
            CalendarCache.start < day_end.isoformat(),
        )
        .order_by(CalendarCache.start.asc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    try:
        return parse_iso(row.start).astimezone(zone)
    except ValueError:
        return None


async def _optimal_sleep_duration(
    session: AsyncSession, target: date, tz: str,
) -> tuple[float, int]:
    """Returns (duration_minutes, n_qualifying_days)."""
    end = target
    start = target - timedelta(days=LOOKBACK_DAYS)
    sleep_rows = await metric_for_day_range(session, "sleep_duration_min", start, end, tz)
    readiness_rows = await metric_for_day_range(session, "readiness_score", start, end, tz)

    # Index readiness by local date.
    zone = ZoneInfo(tz)
    by_date: dict[date, float] = {}
    for r in readiness_rows:
        try:
            d = parse_iso(r.timestamp).astimezone(zone).date()
            by_date[d] = float(r.value)
        except ValueError:
            continue

    qualifying: list[float] = []
    for s in sleep_rows:
        try:
            sleep_day = parse_iso(s.timestamp).astimezone(zone).date()
        except ValueError:
            continue
        next_day = sleep_day + timedelta(days=1)
        next_readiness = by_date.get(next_day)
        if next_readiness is not None and next_readiness >= READINESS_GOOD_THRESHOLD:
            qualifying.append(float(s.value))

    if len(qualifying) < MIN_QUALIFYING_DAYS:
        return FALLBACK_DURATION_MIN, len(qualifying)
    return median(qualifying), len(qualifying)


async def _today_caffeine_after_cutoff(
    session: AsyncSession, target: date, tz: str, cutoff_hour: int,
) -> list[datetime]:
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
    cutoff_hour_dt = datetime.combine(target, time(hour=cutoff_hour), tzinfo=zone)
    out: list[datetime] = []
    for row in (await session.execute(stmt)).scalars().all():
        try:
            data = json.loads(row.data)
        except json.JSONDecodeError:
            continue
        kind = str(data.get("kind") or "").lower()
        if not any(w in kind for w in ("coffee", "tea", "latte", "espresso", "cappuccino", "americano", "matcha", "energy")):
            continue
        try:
            ts = parse_iso(row.timestamp).astimezone(zone)
        except ValueError:
            continue
        if ts >= cutoff_hour_dt:
            out.append(ts)
    return out


async def _late_high_intensity_workouts(
    session: AsyncSession, target: date, tz: str, bedtime: datetime,
) -> list[datetime]:
    zone = ZoneInfo(tz)
    day_start = datetime.combine(target, time.min, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Entry)
        .where(
            Entry.type == "workout_manual",
            Entry.timestamp >= day_start.isoformat(),
            Entry.timestamp < day_end.isoformat(),
        )
    )
    out: list[datetime] = []
    window = timedelta(hours=LATE_WORKOUT_WINDOW_H)
    for row in (await session.execute(stmt)).scalars().all():
        try:
            data = json.loads(row.data)
        except json.JSONDecodeError:
            continue
        if data.get("intensity") != "high":
            continue
        try:
            ts = parse_iso(row.timestamp).astimezone(zone)
        except ValueError:
            continue
        if (bedtime - ts) <= window and ts <= bedtime:
            out.append(ts)
    return out


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        h_str, m_str = value.split(":", 1)
        h, m = int(h_str), int(m_str)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


async def compute_sleep_window(
    session: AsyncSession, *, target: date, tz: str,
) -> SleepWindowOutput:
    """Compute F4 for `target` (the date you're going to sleep on).

    Profile inputs (read from the singleton row, all optional):
    - target_sleep_min — overrides the 7.5h fallback when there aren't enough
      qualifying days yet
    - target_wake_time (HH:MM) — overrides the 08:00 default when there's no
      calendar event tomorrow
    - caffeine_cutoff_hour — overrides the 14:00 default for the late-caffeine
      flag
    """
    zone = ZoneInfo(tz)
    profile = await session.get(Profile, 1)

    # Wake time
    wake_hour = DEFAULT_WAKE_HOUR
    wake_minute = 0
    wake_source = "default 08:00"
    if profile is not None and profile.target_wake_time:
        parsed = _parse_hhmm(profile.target_wake_time)
        if parsed is not None:
            wake_hour, wake_minute = parsed
            wake_source = f"profile target {profile.target_wake_time}"

    first_event = await _first_event_tomorrow(session, target, tz)
    if first_event is None:
        wake = datetime.combine(
            target + timedelta(days=1),
            time(hour=wake_hour, minute=wake_minute),
            tzinfo=zone,
        )
        wake_note = f"no event tomorrow — using {wake_source}"
    else:
        wake = first_event - timedelta(minutes=30)
        wake_note = f"30 min before first event {first_event.strftime('%H:%M')}"

    duration_min, qualifying_days = await _optimal_sleep_duration(session, target, tz)
    using_fallback = (
        duration_min == FALLBACK_DURATION_MIN
        and qualifying_days < MIN_QUALIFYING_DAYS
    )
    profile_target_used = False
    if using_fallback and profile is not None and profile.target_sleep_min:
        duration_min = float(profile.target_sleep_min)
        profile_target_used = True

    bedtime = wake - timedelta(minutes=duration_min)

    # Caffeine cutoff (profile-overridable)
    cutoff_hour = DEFAULT_CAFFEINE_CUTOFF_HOUR
    if profile is not None and profile.caffeine_cutoff_hour is not None:
        cutoff_hour = profile.caffeine_cutoff_hour

    flags: list[str] = []
    late_caffeine = await _today_caffeine_after_cutoff(session, target, tz, cutoff_hour)
    for c in late_caffeine:
        flags.append(
            f"caffeine logged at {c.strftime('%H:%M')} (after {cutoff_hour:02d}:00)",
        )
    late_workouts = await _late_high_intensity_workouts(session, target, tz, bedtime)
    for w in late_workouts:
        flags.append(
            f"high-intensity workout at {w.strftime('%H:%M')} within 3h of bedtime",
        )

    if using_fallback and not profile_target_used:
        flags.append(
            f"using fallback 7.5h target ({qualifying_days} qualifying days < {MIN_QUALIFYING_DAYS})",
        )
    elif profile_target_used:
        h, m = divmod(int(duration_min), 60)
        flags.append(
            f"using profile target {h}h{m:02d}m ({qualifying_days} qualifying days < {MIN_QUALIFYING_DAYS})",
        )

    return SleepWindowOutput(
        date=target.isoformat(),
        bedtime=bedtime.isoformat(),
        wake_time=wake.isoformat(),
        target_duration_min=duration_min,
        flags=flags,
        inputs={
            "first_event_tomorrow": first_event.isoformat() if first_event else None,
            "qualifying_days_for_baseline": qualifying_days,
            "wake_derivation": wake_note,
            "profile_target_used": profile_target_used,
            "caffeine_cutoff_hour": cutoff_hour,
        },
    )


__all__ = ["compute_sleep_window"]
