"""F7 Stage A — deterministic weekly statistics (SPEC §6).

Pure Python over the ORM. Computes the structured JSON that Stage B (LLM)
synthesizes into prose. The Stage A output is the LLM's only data source —
it cannot invent metrics, correlations, or recommendations outside this
input (system prompt enforces it; this module is the contract).

The week is anchored on ISO weeks (Mon 00:00 → Sun 23:59:59 local). Daily
aggregates pull from the `metrics` table; readiness is recomputed per day
on the fly when no `readiness_score` row was persisted (the daily
readiness_compute job in 2I writes it nightly).

Correlations: Pearson on the 7 daily pairs. Only flagged when |r|>0.5 and
at least 5 paired observations remain after dropping nulls. This filter
keeps tiny-noisy signals out of the prose.

Mean shifts: this-week mean vs the prior 4-week trailing mean+SD. Flagged
when this week's mean is >1 SD above or below trailing.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.habits_adherence import compute_habit_adherence
from lattice.functions.readiness import compute_readiness
from lattice.models import CalendarCache, Entry, Metric

logger = logging.getLogger(__name__)

# Metrics whose daily averages we report in Stage A.
DAILY_METRICS = (
    "sleep_score",
    "sleep_duration_min",
    "hrv_overnight_avg",
    "resting_hr",
    "stress_avg",
)

# Correlation thresholds (SPEC §6 F7).
CORR_R_THRESHOLD = 0.5
CORR_MIN_N = 5

# Mean-shift threshold: flag if |this_week_mean − trailing_mean| > 1 SD.
MEAN_SHIFT_SD_THRESHOLD = 1.0
TRAILING_WEEKS = 4


# --------------------------------------------------------------------------- #
# Output dataclasses (mirrored as Pydantic models in schemas/reports.py)
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class DailyAggregate:
    date: str  # YYYY-MM-DD
    readiness: int | None
    sleep_score: float | None
    sleep_duration_min: float | None
    hrv_overnight_avg: float | None
    resting_hr: float | None
    stress_avg: float | None


@dataclass(slots=True)
class BestWorstDay:
    date: str
    readiness: int
    reason: str  # short rationale


@dataclass(slots=True)
class HabitWeekStat:
    habit_id: int
    name: str
    target_per_week: int
    completed_this_week: int
    week_completion_pct: float
    current_streak_days: int


@dataclass(slots=True)
class Correlation:
    label: str       # e.g. "caffeine_time × sleep_score"
    r: float
    n: int
    direction: str   # "positive" | "negative"


@dataclass(slots=True)
class MeanShift:
    metric: str
    this_week_mean: float
    trailing_mean: float
    trailing_sd: float
    delta_sd: float        # signed: (this − trailing) / trailing_sd
    direction: str         # "up" | "down"


@dataclass(slots=True)
class WeeklyStats:
    iso_week: str
    week_start: str  # YYYY-MM-DD (Mon)
    week_end: str    # YYYY-MM-DD (Sun)
    daily: list[DailyAggregate] = field(default_factory=list)
    averages: dict[str, float | None] = field(default_factory=dict)
    best_day: BestWorstDay | None = None
    worst_day: BestWorstDay | None = None
    habits: list[HabitWeekStat] = field(default_factory=list)
    correlations: list[Correlation] = field(default_factory=list)
    mean_shifts: list[MeanShift] = field(default_factory=list)
    coverage_notes: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        """Stable, JSON-serializable view passed to the LLM as Stage B input."""
        return {
            "iso_week": self.iso_week,
            "week_start": self.week_start,
            "week_end": self.week_end,
            "daily": [asdict(d) for d in self.daily],
            "averages": self.averages,
            "best_day": asdict(self.best_day) if self.best_day else None,
            "worst_day": asdict(self.worst_day) if self.worst_day else None,
            "habits": [asdict(h) for h in self.habits],
            "correlations": [asdict(c) for c in self.correlations],
            "mean_shifts": [asdict(m) for m in self.mean_shifts],
            "coverage_notes": self.coverage_notes,
        }


# --------------------------------------------------------------------------- #
# Week helpers
# --------------------------------------------------------------------------- #


def iso_week_bounds(target: date) -> tuple[date, date, str]:
    """Return (monday, sunday, 'YYYY-Www') for the ISO week containing `target`."""
    iso_year, iso_week, _ = target.isocalendar()
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    sunday = monday + timedelta(days=6)
    return monday, sunday, f"{iso_year}-W{iso_week:02d}"


def _day_iso_start(day: date, tz: str) -> str:
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(tz)).isoformat()


def _day_iso_end(day: date, tz: str) -> str:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo(tz)).isoformat()


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


def _sd(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r over paired xs/ys. Returns None if undefined (n<2 or zero variance)."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    return sxy / math.sqrt(sxx * syy)


# --------------------------------------------------------------------------- #
# Daily metric fetch
# --------------------------------------------------------------------------- #


async def _daily_metric_value(
    session: AsyncSession, name: str, day: date, tz: str,
) -> float | None:
    """Most recent row for `name` whose timestamp falls in [day_start, day_end)."""
    stmt = (
        select(Metric.value)
        .where(
            Metric.metric_name == name,
            Metric.timestamp >= _day_iso_start(day, tz),
            Metric.timestamp < _day_iso_end(day, tz),
        )
        .order_by(Metric.timestamp.desc())
        .limit(1)
    )
    val = (await session.execute(stmt)).scalar_one_or_none()
    return float(val) if val is not None else None


async def _readiness_for(session: AsyncSession, day: date, tz: str) -> int | None:
    """Try persisted readiness_score row first; else recompute on the fly."""
    persisted = await _daily_metric_value(session, "readiness_score", day, tz)
    if persisted is not None:
        return int(round(persisted))
    # On-the-fly fallback. Only return if there was *any* component data
    # for the day — otherwise F1 returns 0 which would skew best/worst.
    out = await compute_readiness(session, target=day, tz=tz)
    if out.score == 0 and not out.explanation.components:
        return None
    return out.score


async def _daily_aggregates(
    session: AsyncSession, monday: date, sunday: date, tz: str,
) -> list[DailyAggregate]:
    out: list[DailyAggregate] = []
    d = monday
    while d <= sunday:
        ag = DailyAggregate(
            date=d.isoformat(),
            readiness=await _readiness_for(session, d, tz),
            sleep_score=await _daily_metric_value(session, "sleep_score", d, tz),
            sleep_duration_min=await _daily_metric_value(
                session, "sleep_duration_min", d, tz,
            ),
            hrv_overnight_avg=await _daily_metric_value(
                session, "hrv_overnight_avg", d, tz,
            ),
            resting_hr=await _daily_metric_value(session, "resting_hr", d, tz),
            stress_avg=await _daily_metric_value(session, "stress_avg", d, tz),
        )
        out.append(ag)
        d += timedelta(days=1)
    return out


def _averages(daily: list[DailyAggregate]) -> dict[str, float | None]:
    keys: tuple[str, ...] = (
        "readiness",
        "sleep_score",
        "sleep_duration_min",
        "hrv_overnight_avg",
        "resting_hr",
        "stress_avg",
    )
    out: dict[str, float | None] = {}
    for k in keys:
        vals: list[float] = []
        for d in daily:
            v = getattr(d, k)
            if v is not None:
                vals.append(float(v))
        out[k] = round(sum(vals) / len(vals), 2) if vals else None
    return out


def _best_worst(daily: list[DailyAggregate]) -> tuple[BestWorstDay | None, BestWorstDay | None]:
    with_score = [(d, d.readiness) for d in daily if d.readiness is not None]
    if not with_score:
        return None, None
    best = max(with_score, key=lambda p: p[1])
    worst = min(with_score, key=lambda p: p[1])
    return (
        BestWorstDay(date=best[0].date, readiness=best[1], reason=_explain_score(best[0])),
        BestWorstDay(date=worst[0].date, readiness=worst[1], reason=_explain_score(worst[0])),
    )


def _explain_score(d: DailyAggregate) -> str:
    bits: list[str] = []
    if d.sleep_score is not None:
        bits.append(f"sleep {d.sleep_score:.0f}")
    if d.hrv_overnight_avg is not None:
        bits.append(f"hrv {d.hrv_overnight_avg:.0f}")
    if d.resting_hr is not None:
        bits.append(f"rhr {d.resting_hr:.0f}")
    return ", ".join(bits) if bits else "(component data sparse)"


# --------------------------------------------------------------------------- #
# Habits, correlations, mean shifts
# --------------------------------------------------------------------------- #


async def _habits(
    session: AsyncSession, monday: date, sunday: date, today: date,
) -> list[HabitWeekStat]:
    adherence = await compute_habit_adherence(
        session, from_=monday, to=sunday, today=today,
    )
    out: list[HabitWeekStat] = []
    for item in adherence.items:
        # Completed-this-week is derivable from the percentage and target.
        # We just round to nearest integer count, capped at 7.
        completed_count = round(item.week_completion_pct / 100.0 * item.target_per_week)
        completed_count = max(0, min(7, completed_count))
        out.append(
            HabitWeekStat(
                habit_id=item.habit_id,
                name=item.name,
                target_per_week=item.target_per_week,
                completed_this_week=completed_count,
                week_completion_pct=item.week_completion_pct,
                current_streak_days=item.current_streak_days,
            ),
        )
    return out


async def _caffeine_vs_sleep(
    session: AsyncSession, monday: date, sunday: date, tz: str,
) -> Correlation | None:
    """Latest coffee-time-of-day (hours past midnight) vs that night's sleep_score.

    Pairs: (latest coffee hour on day D, sleep_score recorded for day D+1).
    Drop days with no coffee or no sleep_score.
    """
    pairs: list[tuple[float, float]] = []
    d = monday
    while d <= sunday:
        # Latest coffee entry on day d
        rows = (
            await session.execute(
                select(Entry).where(
                    and_(
                        Entry.type == "drink",
                        Entry.timestamp >= _day_iso_start(d, tz),
                        Entry.timestamp < _day_iso_end(d, tz),
                    ),
                ).order_by(Entry.timestamp.desc()),
            )
        ).scalars().all()
        latest_coffee_hour: float | None = None
        for r in rows:
            try:
                data = json.loads(r.data)
            except json.JSONDecodeError:
                continue
            if data.get("kind") != "coffee":
                continue
            ts = datetime.fromisoformat(r.timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ZoneInfo(tz))
            ts_local = ts.astimezone(ZoneInfo(tz))
            latest_coffee_hour = ts_local.hour + ts_local.minute / 60.0
            break  # rows are DESC; first is latest
        if latest_coffee_hour is not None:
            next_sleep = await _daily_metric_value(
                session, "sleep_score", d + timedelta(days=1), tz,
            )
            if next_sleep is not None:
                pairs.append((latest_coffee_hour, next_sleep))
        d += timedelta(days=1)
    if len(pairs) < CORR_MIN_N:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    r = _pearson(xs, ys)
    if r is None or abs(r) < CORR_R_THRESHOLD:
        return None
    return Correlation(
        label="caffeine_time × next-night sleep_score",
        r=round(r, 3),
        n=len(pairs),
        direction="positive" if r > 0 else "negative",
    )


async def _workout_vs_hrv(
    session: AsyncSession, monday: date, sunday: date, tz: str,
) -> Correlation | None:
    """Workout intensity (low=1, medium=2, high=3) on day D vs HRV on day D+1."""
    intensity_map = {"low": 1.0, "medium": 2.0, "high": 3.0}
    pairs: list[tuple[float, float]] = []
    d = monday
    while d <= sunday:
        rows = (
            await session.execute(
                select(Entry).where(
                    and_(
                        Entry.type == "workout_manual",
                        Entry.timestamp >= _day_iso_start(d, tz),
                        Entry.timestamp < _day_iso_end(d, tz),
                    ),
                ),
            )
        ).scalars().all()
        peak: float | None = None
        for r in rows:
            try:
                data = json.loads(r.data)
            except json.JSONDecodeError:
                continue
            val = intensity_map.get(data.get("intensity", ""))
            if val is not None and (peak is None or val > peak):
                peak = val
        if peak is not None:
            next_hrv = await _daily_metric_value(
                session, "hrv_overnight_avg", d + timedelta(days=1), tz,
            )
            if next_hrv is not None:
                pairs.append((peak, next_hrv))
        d += timedelta(days=1)
    if len(pairs) < CORR_MIN_N:
        return None
    r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    if r is None or abs(r) < CORR_R_THRESHOLD:
        return None
    return Correlation(
        label="workout_intensity × next-day hrv",
        r=round(r, 3),
        n=len(pairs),
        direction="positive" if r > 0 else "negative",
    )


async def _meetings_vs_energy(
    session: AsyncSession, monday: date, sunday: date, tz: str,
) -> Correlation | None:
    """Total meeting hours on day D vs mean `energy` entry score on day D."""
    pairs: list[tuple[float, float]] = []
    d = monday
    while d <= sunday:
        events = (
            await session.execute(
                select(CalendarCache).where(
                    and_(
                        CalendarCache.is_all_day == 0,
                        CalendarCache.start >= _day_iso_start(d, tz),
                        CalendarCache.start < _day_iso_end(d, tz),
                    ),
                ),
            )
        ).scalars().all()
        total_minutes = 0.0
        for ev in events:
            try:
                s = datetime.fromisoformat(ev.start)
                e = datetime.fromisoformat(ev.end)
            except ValueError:
                continue
            total_minutes += (e - s).total_seconds() / 60.0
        meeting_hours = total_minutes / 60.0
        # Energy entries on same day
        energy_rows = (
            await session.execute(
                select(Entry).where(
                    and_(
                        Entry.type == "energy",
                        Entry.timestamp >= _day_iso_start(d, tz),
                        Entry.timestamp < _day_iso_end(d, tz),
                    ),
                ),
            )
        ).scalars().all()
        scores: list[float] = []
        for r in energy_rows:
            try:
                data = json.loads(r.data)
            except json.JSONDecodeError:
                continue
            s_val = data.get("score")
            if isinstance(s_val, int | float):
                scores.append(float(s_val))
        if scores and meeting_hours > 0:
            pairs.append((meeting_hours, sum(scores) / len(scores)))
        d += timedelta(days=1)
    if len(pairs) < CORR_MIN_N:
        return None
    r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    if r is None or abs(r) < CORR_R_THRESHOLD:
        return None
    return Correlation(
        label="meeting_hours × energy",
        r=round(r, 3),
        n=len(pairs),
        direction="positive" if r > 0 else "negative",
    )


async def _mean_shifts(
    session: AsyncSession, monday: date, sunday: date, tz: str,
) -> list[MeanShift]:
    """Compare this week's daily-mean for each metric to the prior 4-week trailing.

    Trailing window: the 4 ISO weeks immediately before this one
    (28 days, Mon..Sun*4). Flag if |delta| > 1 trailing SD.
    """
    trailing_start = monday - timedelta(days=7 * TRAILING_WEEKS)
    trailing_end = monday - timedelta(days=1)

    out: list[MeanShift] = []
    for name in DAILY_METRICS:
        this_vals: list[float] = []
        trailing_vals: list[float] = []
        d = monday
        while d <= sunday:
            v = await _daily_metric_value(session, name, d, tz)
            if v is not None:
                this_vals.append(v)
            d += timedelta(days=1)
        d = trailing_start
        while d <= trailing_end:
            v = await _daily_metric_value(session, name, d, tz)
            if v is not None:
                trailing_vals.append(v)
            d += timedelta(days=1)
        if not this_vals or len(trailing_vals) < 2:
            continue
        this_mean = sum(this_vals) / len(this_vals)
        trailing_mean = sum(trailing_vals) / len(trailing_vals)
        trailing_sd = _sd(trailing_vals, trailing_mean)
        if trailing_sd == 0:
            continue
        delta_sd = (this_mean - trailing_mean) / trailing_sd
        if abs(delta_sd) < MEAN_SHIFT_SD_THRESHOLD:
            continue
        out.append(
            MeanShift(
                metric=name,
                this_week_mean=round(this_mean, 2),
                trailing_mean=round(trailing_mean, 2),
                trailing_sd=round(trailing_sd, 2),
                delta_sd=round(delta_sd, 2),
                direction="up" if delta_sd > 0 else "down",
            ),
        )
    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


async def compute_weekly_stats(
    session: AsyncSession, *, target: date, tz: str | None = None,
) -> WeeklyStats:
    """Compute Stage A statistics for the ISO week containing `target`.

    `target` can be any day in the week; the function snaps to Mon..Sun.
    """
    zone = tz or settings.timezone
    monday, sunday, iso_week = iso_week_bounds(target)
    today = datetime.now(ZoneInfo(zone)).date()
    # When stats are computed for a past ISO week, "this week's habit
    # completion" must look at the target week, not the trailing 7 days of
    # the real calendar. Clamp `today` into [monday, sunday] so the F8
    # adherence window is the requested week, not today minus 6.
    if today > sunday:
        today = sunday
    elif today < monday:
        today = monday

    daily = await _daily_aggregates(session, monday, sunday, zone)
    averages = _averages(daily)
    best, worst = _best_worst(daily)
    habits = await _habits(session, monday, sunday, today)

    correlations: list[Correlation] = []
    for fn in (_caffeine_vs_sleep, _workout_vs_hrv, _meetings_vs_energy):
        try:
            c = await fn(session, monday, sunday, zone)
        except Exception:  # noqa: BLE001 — never fail the report on a single corr
            logger.exception("correlation %s failed", fn.__name__)
            c = None
        if c is not None:
            correlations.append(c)

    mean_shifts = await _mean_shifts(session, monday, sunday, zone)

    coverage_notes: list[str] = []
    days_with_readiness = sum(1 for d in daily if d.readiness is not None)
    if days_with_readiness < 5:
        coverage_notes.append(
            f"sparse data: {days_with_readiness}/7 days have readiness — report may be noisy",
        )

    return WeeklyStats(
        iso_week=iso_week,
        week_start=monday.isoformat(),
        week_end=sunday.isoformat(),
        daily=daily,
        averages=averages,
        best_day=best,
        worst_day=worst,
        habits=habits,
        correlations=correlations,
        mean_shifts=mean_shifts,
        coverage_notes=coverage_notes,
    )


__all__ = [
    "BestWorstDay",
    "CORR_MIN_N",
    "CORR_R_THRESHOLD",
    "Correlation",
    "DAILY_METRICS",
    "DailyAggregate",
    "HabitWeekStat",
    "MEAN_SHIFT_SD_THRESHOLD",
    "MeanShift",
    "TRAILING_WEEKS",
    "WeeklyStats",
    "compute_weekly_stats",
    "iso_week_bounds",
]
