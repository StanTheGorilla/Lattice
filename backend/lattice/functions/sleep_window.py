"""F4 — Sleep Window (SPEC §6).

The target duration is built to be PRESCRIPTIVE and personalized, using every
recovery signal Garmin records — not a mirror of a chronically short habit and
not a flat age stereotype:

  1. Healthy envelope — the age-appropriate range (AASM/AAP: teens 8–10h,
     adults 7–9h), read from Profile.birthday. This is the floor/ceiling.
  2. Position inside the envelope — a recovery-debt fraction in [0,1] derived
     from the trailing week vs the user's own 60-day baseline across HRV,
     resting HR, sleep score, efficiency, overnight recharge, restlessness,
     readiness, AND how far recent sleep sits below the healthy floor. More
     depleted → target the upper part of the range; well-recovered → the floor.
  3. Acute nudge — today's stress / body-battery / HRV vs a 14-day baseline
     shift tonight up (worse) or down (better), bounded.

  wake = first_event_tomorrow − 30 min   (if no morning event → 08:00 local)
  ideal_bedtime = wake − target_duration

Feasibility: when you open this past your ideal bedtime (the classic "it's
already midnight" case) the headline switches to the best window still
achievable — sleep now until wake — with the ideal kept as a secondary note.

Flags:
  - caffeine logged after the cutoff hour on `target`
  - high-intensity workout within 3h of the planned bedtime
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import (
    clamp,
    compute_baseline,
    metric_for_day_range,
    metric_on_date,
    parse_iso,
)
from lattice.models import CalendarCache, Entry, Profile
from lattice.schemas.functions import SleepWindowOutput

DEFAULT_WAKE_HOUR = 8
DEFAULT_CAFFEINE_CUTOFF_HOUR = 14
LATE_WORKOUT_WINDOW_H = 3
# Only events starting before this local hour are treated as wake-anchoring
# commitments. Evening events (medication reminders, dinners) must not pull
# the computed wake-time forward into the afternoon.
MORNING_EVENT_LATEST_HOUR = 13

# Recovery-debt model — where inside the healthy range tonight's target sits.
# The trailing week is compared to the user's own 60-day distribution for each
# signal; a signal's oriented z-score is mapped to a [0,1] depletion fraction,
# and the mean across signals (plus a direct sleep-debt term) decides how far
# above the healthy floor to aim.
DEBT_DISTRIBUTION_DAYS = 60
RECENT_NIGHTS = 7
DEBT_Z_SPAN = 1.5  # oriented z in [-span, +span] maps to depletion [0, 1]
DEBT_DEFICIT_BAND_MIN = 120.0  # recent sleep this far below floor saturates debt

# Each signal: (metric, orientation, label). orientation = +1 means a HIGHER
# value implies WORSE recovery (more depleted); -1 means a higher value implies
# BETTER recovery. The fraction is always oriented to "recovery debt".
_DEPLETION_SIGNALS: tuple[tuple[str, int, str], ...] = (
    ("hrv_overnight_avg", -1, "HRV"),
    ("resting_hr", +1, "resting HR"),
    ("sleep_score", -1, "sleep score"),
    ("sleep_efficiency", -1, "sleep efficiency"),
    ("body_battery_charged", -1, "overnight recharge"),
    ("restless_moments_count", +1, "restlessness"),
    ("readiness_score", -1, "readiness"),
)

# Acute adjustment — nudges the target up or down based on TODAY's recovery
# signals relative to a trailing 14-day baseline. Orthogonal to the chronic
# debt model above: this is "how taxed are you right now", bounded so one rough
# day can't blow past the healthy envelope.
RECOVERY_BASELINE_DAYS = 14
RECOVERY_MIN_BASELINE_N = 5  # need a real baseline before trusting the z-score
RECOVERY_Z_CLAMP = 2.0  # ignore extreme outliers past ±2σ
RECOVERY_MIN_PER_SIGMA = 15.0  # minutes shifted per 1σ of "worse recovery"
RECOVERY_MAX_INCREASE = 45.0  # never add more than 45 min for a bad day
RECOVERY_MAX_DECREASE = 20.0  # never trim more than 20 min for a great day

# direction = +1 means a value ABOVE baseline implies worse recovery.
_RECOVERY_SIGNALS: tuple[tuple[str, int, str, str], ...] = (
    ("stress_avg", +1, "elevated stress", "low stress"),
    ("body_battery_min", -1, "low body battery", "high body battery"),
    ("hrv_overnight_avg", -1, "low HRV", "high HRV"),
)

# Age-appropriate healthy sleep ranges (AASM / AAP consensus), in minutes, as
# (max_age_inclusive, floor, ceiling).
_HEALTHY_BOUNDS_MIN: tuple[tuple[int, float, float], ...] = (
    (5, 600.0, 780.0),    # ≤5y    10–13h
    (12, 540.0, 720.0),   # 6–12y   9–12h
    (17, 480.0, 600.0),   # 13–17y  8–10h
    (64, 420.0, 540.0),   # 18–64y  7–9h
)
_HEALTHY_BOUNDS_SENIOR = (420.0, 480.0)   # ≥65y  7–8h
_HEALTHY_BOUNDS_DEFAULT = (420.0, 540.0)  # unknown age → adult 7–9h


async def _first_event_tomorrow(
    session: AsyncSession, target: date, tz: str,
) -> datetime | None:
    """Earliest morning timed event on the day after `target` (in `tz`).

    Filters out events whose local start hour is ≥ MORNING_EVENT_LATEST_HOUR —
    afternoon/evening commitments (medication reminders, dinners) must not
    pull the wake anchor forward into the afternoon.
    """
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
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        try:
            start = parse_iso(row.start).astimezone(zone)
        except ValueError:
            continue
        if start.hour < MORNING_EVENT_LATEST_HOUR:
            return start
    return None


async def _signal_series(
    session: AsyncSession, name: str, target: date, tz: str,
) -> dict[date, float]:
    """One value per night for `name` over [target−60d, target−1d], keyed by
    local date. Excludes `target` itself (that night hasn't happened yet)."""
    start = target - timedelta(days=DEBT_DISTRIBUTION_DAYS)
    end = target - timedelta(days=1)
    rows = await metric_for_day_range(session, name, start, end, tz)
    zone = ZoneInfo(tz)
    by_date: dict[date, float] = {}
    for r in rows:
        try:
            d = parse_iso(r.timestamp).astimezone(zone).date()
        except ValueError:
            continue
        by_date[d] = float(r.value)
    return by_date


def _recent_values(series: dict[date, float], n: int) -> list[float]:
    """Values for the `n` most recent dates present in `series`."""
    return [series[d] for d in sorted(series)[-n:]]


async def _recovery_debt(
    session: AsyncSession, target: date, tz: str, *, floor_min: float,
) -> tuple[float, float | None, list[str], int]:
    """How depleted the user is, as a fraction in [0,1] (0 = fully recovered).

    Compares the trailing week to the user's own 60-day distribution across the
    depletion signals, plus a direct sleep-debt term (recent sleep below the
    healthy floor). Returns (debt_fraction, recent_sleep_mean_min, basis, n).

    With no usable history returns (0.5, None, [], 0) — a neutral mid-range
    position — so a brand-new dataset gets sane guidance instead of a wild swing.
    """
    marker_fracs: list[float] = []
    depleted: list[str] = []
    recovered: list[str] = []
    for name, orient, label in _DEPLETION_SIGNALS:
        series = await _signal_series(session, name, target, tz)
        dist = list(series.values())
        if len(dist) < 2:
            continue
        sd = pstdev(dist)
        if sd <= 0.0:
            continue
        recent = _recent_values(series, RECENT_NIGHTS)
        if not recent:
            continue
        z = orient * (mean(recent) - mean(dist)) / sd
        frac = clamp((z + DEBT_Z_SPAN) / (2 * DEBT_Z_SPAN), 0.0, 1.0)
        marker_fracs.append(frac)
        if frac >= 0.6:
            depleted.append(label)
        elif frac <= 0.4:
            recovered.append(label)

    sleep_series = await _signal_series(session, "sleep_duration_min", target, tz)
    recent_sleep = _recent_values(sleep_series, RECENT_NIGHTS)
    recent_sleep_mean = mean(recent_sleep) if recent_sleep else None
    debt_frac: float | None = None
    if recent_sleep_mean is not None:
        debt_frac = clamp(
            (floor_min - recent_sleep_mean) / DEBT_DEFICIT_BAND_MIN, 0.0, 1.0,
        )

    marker_mean = mean(marker_fracs) if marker_fracs else None
    if marker_mean is not None and debt_frac is not None:
        debt = (marker_mean + debt_frac) / 2.0
    elif marker_mean is not None:
        debt = marker_mean
    elif debt_frac is not None:
        debt = debt_frac
    else:
        return 0.5, None, [], 0

    n_signals = len(marker_fracs) + (1 if debt_frac is not None else 0)
    basis: list[str] = []
    if recent_sleep_mean is not None and debt_frac is not None and debt_frac > 0.05:
        basis.append(
            f"recent sleep {_hm(recent_sleep_mean)} below {_hm(floor_min)} floor",
        )
    if depleted:
        basis.append("recovery below baseline (" + ", ".join(depleted) + ")")
    elif recovered:
        basis.append("recovery strong (" + ", ".join(recovered) + ")")
    return debt, recent_sleep_mean, basis, n_signals


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
        # P1-3: F4 and F5 agree — an entry is caffeinated iff caffeine_mg > 0.
        # Legacy "coffee"-kind entries pre-dating the caffeine_mg field still
        # count (matches F5's legacy fallback). Substring-on-kind misses
        # cola, yerba mate, kombucha, etc.
        caffeine_mg = data.get("caffeine_mg")
        kind = str(data.get("kind") or "").lower()
        if not (
            (caffeine_mg is not None and float(caffeine_mg) > 0)
            or kind == "coffee"
        ):
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


async def _recovery_adjustment(
    session: AsyncSession, target: date, tz: str,
) -> tuple[float, list[str]]:
    """Minutes to add to (or trim from) the base target for `target` based on
    TODAY's stress / body-battery / HRV vs their trailing 14-day baselines.

    Returns (0.0, []) whenever no signal has a usable baseline, so behaviour is
    unchanged for fresh datasets and for any caller without recovery metrics.
    """
    recovery_zs: list[float] = []
    reasons: list[str] = []
    for name, direction, worse_label, better_label in _RECOVERY_SIGNALS:
        baseline = await compute_baseline(
            session, name, days=RECOVERY_BASELINE_DAYS, before=target, tz=tz,
        )
        if (
            baseline.mean is None
            or baseline.sd is None
            or baseline.sd <= 0.0
            or baseline.n < RECOVERY_MIN_BASELINE_N
        ):
            continue
        today = await metric_on_date(session, name, target, tz)
        if today is None:
            continue
        z = (float(today.value) - baseline.mean) / baseline.sd
        recovery_z = clamp(z * direction, -RECOVERY_Z_CLAMP, RECOVERY_Z_CLAMP)
        recovery_zs.append(recovery_z)
        if recovery_z >= 0.5:
            reasons.append(worse_label)
        elif recovery_z <= -0.5:
            reasons.append(better_label)

    if not recovery_zs:
        return 0.0, []

    mean_z = sum(recovery_zs) / len(recovery_zs)
    adjustment = clamp(
        mean_z * RECOVERY_MIN_PER_SIGMA,
        -RECOVERY_MAX_DECREASE,
        RECOVERY_MAX_INCREASE,
    )
    return adjustment, reasons


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        h_str, m_str = value.split(":", 1)
        h, m = int(h_str), int(m_str)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, AttributeError):
        pass
    return None


def _age_on(birthday: str | None, on: date) -> int | None:
    """Whole years old on `on`, from a 'YYYY-MM-DD' birthday (None if unusable)."""
    if not birthday:
        return None
    try:
        b = date.fromisoformat(birthday)
    except ValueError:
        return None
    years = on.year - b.year - ((on.month, on.day) < (b.month, b.day))
    return years if years >= 0 else None


def _healthy_sleep_bounds_min(age: int | None) -> tuple[float, float]:
    """Healthy [floor, ceiling] sleep minutes for `age`; adult 7–9h if unknown."""
    if age is None:
        return _HEALTHY_BOUNDS_DEFAULT
    for max_age, floor_min, ceil_min in _HEALTHY_BOUNDS_MIN:
        if age <= max_age:
            return floor_min, ceil_min
    return _HEALTHY_BOUNDS_SENIOR


def _hm(minutes: float) -> str:
    """Format minutes as 'Hh MMm' for human-readable flags."""
    h, m = divmod(int(round(minutes)), 60)
    return f"{h}h{m:02d}m"


async def compute_sleep_window(
    session: AsyncSession, *, target: date, tz: str, now: datetime | None = None,
) -> SleepWindowOutput:
    """Compute F4 for `target` (the date you're going to sleep on).

    `now` (defaults to the real clock in `tz`) drives the feasibility switch:
    when called past the ideal bedtime, the headline becomes the best window
    still achievable. Pass it explicitly in tests.

    Profile inputs (singleton row, all optional):
    - birthday — sets the healthy range; without it, adult 7–9h is assumed
    - target_sleep_min — explicit base target, overriding the computed one
    - target_wake_time (HH:MM) — overrides 08:00 when there's no morning event
    - caffeine_cutoff_hour — overrides the 14:00 late-caffeine flag
    """
    zone = ZoneInfo(tz)
    profile = await session.get(Profile, 1)
    now_local = now.astimezone(zone) if now is not None else datetime.now(zone)

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

    # Healthy envelope. V-2: read the AI-writable health_targets store first
    # (which falls back to the age-derived seed when no AI row exists).
    age = _age_on(profile.birthday if profile is not None else None, target)
    from lattice.functions.health_targets import get_sleep_bounds_min
    floor_min, ceil_min, floor_source, ceil_source = await get_sleep_bounds_min(
        session, age=age,
    )

    # Position inside the envelope from recovery debt (all signals).
    debt, recent_sleep_mean, debt_basis, n_signals = await _recovery_debt(
        session, target, tz, floor_min=floor_min,
    )
    base_min = floor_min + debt * (ceil_min - floor_min)

    # Explicit profile target overrides the computed base, if set.
    profile_target_used = False
    if profile is not None and profile.target_sleep_min:
        base_min = float(profile.target_sleep_min)
        profile_target_used = True
    base_clamped = clamp(base_min, floor_min, ceil_min)

    # Acute nudge from today's state, then the binding healthy clamp.
    acute_adj, acute_reasons = await _recovery_adjustment(session, target, tz)
    duration_min = clamp(base_min + acute_adj, floor_min, ceil_min)
    applied_acute = round(duration_min - base_clamped)

    ideal_bedtime = wake - timedelta(minutes=duration_min)

    # Feasibility: if we're already past the ideal bedtime (but before wake),
    # switch the headline to the best window still achievable — sleep now.
    feasible = True
    minutes_past_ideal: int | None = None
    achievable_min: int | None = None
    if ideal_bedtime <= now_local < wake:
        feasible = False
        minutes_past_ideal = round((now_local - ideal_bedtime).total_seconds() / 60)
        achievable_min = max(0, round((wake - now_local).total_seconds() / 60))
        bedtime = now_local
        headline_duration = float(achievable_min)
    else:
        bedtime = ideal_bedtime
        headline_duration = duration_min

    # Caffeine cutoff — Profile field still wins (explicit owner choice);
    # otherwise read the AI-writable health_targets store, which falls back
    # to the static 14:00 default when no AI row exists.
    cutoff_hour = DEFAULT_CAFFEINE_CUTOFF_HOUR
    if profile is not None and profile.caffeine_cutoff_hour is not None:
        cutoff_hour = profile.caffeine_cutoff_hour
    else:
        from lattice.functions.health_targets import (
            CAFFEINE_CUTOFF_HOUR_KIND,
            get_target,
        )
        cutoff_target = await get_target(session, CAFFEINE_CUTOFF_HOUR_KIND)
        cutoff_hour = int(round(cutoff_target.value))

    flags: list[str] = []
    age_txt = f" for age {age}" if age is not None else ""
    if profile_target_used:
        flags.append(
            f"using your configured target {_hm(base_min)} "
            f"(healthy range {_hm(floor_min)}–{_hm(ceil_min)}{age_txt})",
        )
    elif n_signals == 0:
        flags.append(
            f"limited recovery history — mid healthy range "
            f"{_hm(base_clamped)}{age_txt}",
        )
    else:
        because = f" — {'; '.join(debt_basis)}" if debt_basis else ""
        flags.append(
            f"targeting {_hm(base_clamped)} in healthy "
            f"{_hm(floor_min)}–{_hm(ceil_min)}{age_txt}{because}",
        )

    acute_basis = ", ".join(acute_reasons) if acute_reasons else None
    if applied_acute >= 5:
        because = f" ({acute_basis})" if acute_basis else ""
        flags.append(f"+{applied_acute} min for today's recovery{because}")
    elif applied_acute <= -5:
        because = f" ({acute_basis})" if acute_basis else ""
        flags.append(f"{applied_acute} min — strong recovery today{because}")

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

    if not feasible:
        flags.append(
            f"past ideal bedtime {ideal_bedtime.strftime('%H:%M')} — "
            f"sleeping now gives {_hm(headline_duration)} before "
            f"{wake.strftime('%H:%M')} wake (target {_hm(duration_min)})",
        )

    return SleepWindowOutput(
        date=target.isoformat(),
        bedtime=bedtime.isoformat(),
        wake_time=wake.isoformat(),
        target_duration_min=headline_duration,
        flags=flags,
        inputs={
            "first_event_tomorrow": first_event.isoformat() if first_event else None,
            "wake_derivation": wake_note,
            "caffeine_cutoff_hour": cutoff_hour,
            "age": age,
            "healthy_floor_min": int(floor_min),
            "healthy_ceiling_min": int(ceil_min),
            "recovery_debt_fraction": round(debt, 2),
            "recovery_debt_basis": "; ".join(debt_basis) if debt_basis else None,
            "recent_sleep_mean_min": (
                round(recent_sleep_mean) if recent_sleep_mean is not None else None
            ),
            "n_recovery_signals": n_signals,
            "within_range_target_min": round(base_clamped),
            "acute_adjustment_min": applied_acute,
            "acute_basis": acute_basis,
            "profile_target_used": profile_target_used,
            "target_duration_min": round(duration_min),
            "ideal_bedtime": ideal_bedtime.isoformat(),
            "feasible": feasible,
            "minutes_past_ideal_bedtime": minutes_past_ideal,
            "achievable_duration_min": achievable_min,
        },
    )


__all__ = ["compute_sleep_window"]
