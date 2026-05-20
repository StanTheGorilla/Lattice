"""Stats aggregator primitives (SPEC §6 — analytical tool surface).

These are the deterministic statistical functions the LLM chat agent calls to
ground its replies. Each function returns a JSON-friendly dict containing
`{median, mean, min, max, p25, p75, sd, n, low_confidence}` plus the original
query parameters echoed back so the LLM can cite them.

Routing convention:
- Names in `SAMPLE_METRIC_NAMES` live in the `metric_samples` table
  (intra-day readings: per-minute HR, per-minute stress, BB samples).
- All other names live in the `metrics` table (daily aggregates).

Date inputs accept either `YYYY-MM-DD` (expanded to midnight / end-of-day local)
or full ISO 8601 strings. Date-range default when both omitted = last 7 days.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric, MetricSample

# Intra-day sample names (live in metric_samples). Anything else is a daily
# aggregate in `metrics`.
SAMPLE_METRIC_NAMES: frozenset[str] = frozenset({"hr", "stress", "body_battery"})

LOW_CONFIDENCE_N = 5
DEFAULT_LOOKBACK_DAYS = 7
DAILY_SERIES_CAP = 365  # safety: never return more than a year of daily rows


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def _now_local() -> datetime:
    return datetime.now(_tz())


def _is_sample(name: str) -> bool:
    return name in SAMPLE_METRIC_NAMES


def _normalize_from(s: str | None, default_days_back: int = DEFAULT_LOOKBACK_DAYS) -> str:
    """Lower-bound timestamp (inclusive). Date-only inputs → midnight local."""
    tz = _tz()
    if s is None:
        d = _now_local().date() - timedelta(days=max(0, default_days_back - 1))
        return datetime.combine(d, time.min, tzinfo=tz).isoformat()
    if len(s) == 10:  # YYYY-MM-DD
        try:
            d = date.fromisoformat(s)
            return datetime.combine(d, time.min, tzinfo=tz).isoformat()
        except ValueError:
            pass
    return s


def _normalize_to(s: str | None) -> str:
    """Upper-bound timestamp (inclusive). Date-only inputs → 23:59:59.999999 local."""
    tz = _tz()
    if s is None:
        d = _now_local().date()
        return datetime.combine(d, time.max, tzinfo=tz).isoformat()
    if len(s) == 10:
        try:
            d = date.fromisoformat(s)
            return datetime.combine(d, time.max, tzinfo=tz).isoformat()
        except ValueError:
            pass
    return s


def _summarize(values: list[float]) -> dict[str, Any]:
    """Median/mean/min/max/p25/p75/sd/n + low_confidence flag.

    All values rounded to 3 decimals to keep tool payloads readable.
    """
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "median": None,
            "mean": None,
            "min": None,
            "max": None,
            "p25": None,
            "p75": None,
            "sd": None,
            "low_confidence": True,
        }

    def r(v: float) -> float:
        return round(float(v), 3)

    s = sorted(values)
    if n >= 4:
        qs = statistics.quantiles(s, n=4, method="inclusive")
        p25, _, p75 = qs[0], qs[1], qs[2]
    elif n >= 2:
        p25, p75 = s[0], s[-1]
    else:
        p25 = p75 = s[0]
    sd = statistics.stdev(s) if n >= 2 else 0.0
    return {
        "n": n,
        "median": r(statistics.median(s)),
        "mean": r(statistics.mean(s)),
        "min": r(s[0]),
        "max": r(s[-1]),
        "p25": r(p25),
        "p75": r(p75),
        "sd": r(sd),
        "low_confidence": n < LOW_CONFIDENCE_N,
    }


async def _fetch_values(
    session: AsyncSession, name: str, from_iso: str, to_iso: str,
) -> list[float]:
    """Read raw `value` column from the right table for `name` over [from, to]."""
    if _is_sample(name):
        stmt = (
            select(MetricSample.value)
            .where(MetricSample.metric_name == name)
            .where(MetricSample.timestamp >= from_iso)
            .where(MetricSample.timestamp <= to_iso)
        )
    else:
        stmt = (
            select(Metric.value)
            .where(Metric.metric_name == name)
            .where(Metric.timestamp >= from_iso)
            .where(Metric.timestamp <= to_iso)
        )
    return [float(v) for v in (await session.execute(stmt)).scalars().all()]


async def _fetch_values_with_ts(
    session: AsyncSession, name: str, from_iso: str, to_iso: str,
) -> list[tuple[str, float]]:
    """As above but returns (timestamp, value) pairs."""
    if _is_sample(name):
        stmt = (
            select(MetricSample.timestamp, MetricSample.value)
            .where(MetricSample.metric_name == name)
            .where(MetricSample.timestamp >= from_iso)
            .where(MetricSample.timestamp <= to_iso)
            .order_by(MetricSample.timestamp)
        )
    else:
        stmt = (
            select(Metric.timestamp, Metric.value)
            .where(Metric.metric_name == name)
            .where(Metric.timestamp >= from_iso)
            .where(Metric.timestamp <= to_iso)
            .order_by(Metric.timestamp)
        )
    return [(str(t), float(v)) for t, v in (await session.execute(stmt)).all()]


def _hour_of(ts: str) -> int | None:
    """Extract hour-of-day from an ISO 8601 string. Returns None on bad input.

    Works because we always store local-time ISO strings (the GMT→local
    conversion happens in the extractors); position 11..13 holds `HH`.
    """
    if len(ts) < 13 or ts[10] != "T":
        try:
            return datetime.fromisoformat(ts).hour
        except ValueError:
            return None
    try:
        return int(ts[11:13])
    except ValueError:
        return None


def _weekday_of(ts: str) -> int | None:
    """0 = Monday … 6 = Sunday."""
    try:
        return datetime.fromisoformat(ts).weekday()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

async def stats_for_metric(
    session: AsyncSession,
    name: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Aggregate stats for `name` over [from, to]. Default range = last 7 days."""
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    values = await _fetch_values(session, name, f, t)
    return {"name": name, "from": f, "to": t, **_summarize(values)}


async def stats_by_hour(
    session: AsyncSession,
    name: str,
    hour_start: int,
    hour_end: int,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Stats for `name` restricted to local-time window `[hour_start, hour_end)`.

    Hour filter only meaningful for intra-day sample metrics (hr, stress,
    body_battery). For daily metrics, returns `error="not_intra_day"`.
    """
    if not (0 <= hour_start < 24 and 0 < hour_end <= 24 and hour_start < hour_end):
        return {"error": "invalid_hours", "name": name}
    if not _is_sample(name):
        return {
            "error": "not_intra_day",
            "name": name,
            "message": (
                f"`{name}` is a daily aggregate; hour windows only apply to "
                f"intra-day metrics: {sorted(SAMPLE_METRIC_NAMES)}. "
                "Use stats_for_metric for daily metrics."
            ),
        }
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, name, f, t)
    filtered = [v for ts, v in pairs if (h := _hour_of(ts)) is not None and hour_start <= h < hour_end]
    return {
        "name": name,
        "from": f,
        "to": t,
        "hour_start": hour_start,
        "hour_end": hour_end,
        **_summarize(filtered),
    }


async def stats_by_weekday(
    session: AsyncSession,
    name: str,
    weekdays: list[int],
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Stats restricted to specific weekdays (0=Mon…6=Sun)."""
    if not weekdays or any(d < 0 or d > 6 for d in weekdays):
        return {"error": "invalid_weekdays", "name": name}
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, name, f, t)
    wset = set(weekdays)
    filtered = [v for ts, v in pairs if (w := _weekday_of(ts)) is not None and w in wset]
    return {
        "name": name,
        "from": f,
        "to": t,
        "weekdays": sorted(weekdays),
        **_summarize(filtered),
    }


async def daily_series(
    session: AsyncSession,
    name: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Per-day values as `[{date, value}, ...]`. For sample names, value = day median.

    Capped at DAILY_SERIES_CAP rows to keep payloads small.
    """
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, name, f, t)
    by_day: dict[str, list[float]] = defaultdict(list)
    for ts, v in pairs:
        by_day[ts[:10]].append(v)
    series: list[dict[str, Any]] = []
    for d in sorted(by_day.keys()):
        vals = by_day[d]
        value = (
            round(statistics.median(vals), 3) if _is_sample(name) else round(vals[0], 3)
        )
        series.append({"date": d, "value": value})
    truncated = len(series) > DAILY_SERIES_CAP
    if truncated:
        series = series[-DAILY_SERIES_CAP:]
    return {
        "name": name,
        "from": f,
        "to": t,
        "n": len(series),
        "truncated": truncated,
        "series": series,
    }


async def compare_windows(
    session: AsyncSession,
    name: str,
    a_from: str | None,
    a_to: str | None,
    b_from: str | None,
    b_to: str | None,
    a_hour_start: int | None = None,
    a_hour_end: int | None = None,
    b_hour_start: int | None = None,
    b_hour_end: int | None = None,
) -> dict[str, Any]:
    """Compare two date windows (optionally with hour filters). Returns both stats
    blocks plus a `delta_pct` (b vs a, on median) and a `significant` flag.

    `significant = abs(median_b - median_a) > sd_a` (rough — formal t-test is
    overkill at this n; flag is advisory).
    """
    async def _block(
        f: str | None, t: str | None, h0: int | None, h1: int | None,
    ) -> dict[str, Any]:
        if h0 is not None and h1 is not None:
            return await stats_by_hour(session, name, h0, h1, f, t)
        return await stats_for_metric(session, name, f, t)

    a = await _block(a_from, a_to, a_hour_start, a_hour_end)
    b = await _block(b_from, b_to, b_hour_start, b_hour_end)
    out: dict[str, Any] = {"name": name, "a": a, "b": b}
    if "error" in a or "error" in b:
        return out
    if a.get("median") is None or b.get("median") is None:
        out["delta_pct"] = None
        out["significant"] = False
        return out
    ma, mb = float(a["median"]), float(b["median"])
    out["delta_pct"] = round((mb - ma) / ma * 100.0, 2) if ma != 0 else None
    sd_a = float(a.get("sd") or 0.0)
    out["significant"] = abs(mb - ma) > sd_a and a.get("n", 0) >= LOW_CONFIDENCE_N and b.get("n", 0) >= LOW_CONFIDENCE_N
    return out


async def correlate(
    session: AsyncSession,
    metric_a: str,
    metric_b: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Pearson correlation between two metrics, paired by calendar day.

    Returns null (and a `reason`) when n<5 or |r|<0.3, to avoid surfacing
    weak/noisy correlations to the LLM.
    """
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs_a = await _fetch_values_with_ts(session, metric_a, f, t)
    pairs_b = await _fetch_values_with_ts(session, metric_b, f, t)

    # Bucket by day, take per-day median (matches Stage A weekly-stats convention).
    def _by_day(pairs: list[tuple[str, float]]) -> dict[str, float]:
        d: dict[str, list[float]] = defaultdict(list)
        for ts, v in pairs:
            d[ts[:10]].append(v)
        return {k: statistics.median(vs) for k, vs in d.items()}

    a_by_day = _by_day(pairs_a)
    b_by_day = _by_day(pairs_b)
    common = sorted(set(a_by_day) & set(b_by_day))
    n = len(common)
    if n < LOW_CONFIDENCE_N:
        return {
            "metric_a": metric_a, "metric_b": metric_b,
            "from": f, "to": t, "n": n, "r": None,
            "reason": f"insufficient data (n={n}, need >= {LOW_CONFIDENCE_N})",
        }
    xs = [a_by_day[d] for d in common]
    ys = [b_by_day[d] for d in common]
    try:
        r = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return {
            "metric_a": metric_a, "metric_b": metric_b,
            "from": f, "to": t, "n": n, "r": None,
            "reason": "zero variance in one or both series",
        }
    if abs(r) < 0.3:
        return {
            "metric_a": metric_a, "metric_b": metric_b,
            "from": f, "to": t, "n": n, "r": round(r, 3),
            "reason": "below |0.3| threshold; not reported as a pattern",
        }
    return {
        "metric_a": metric_a, "metric_b": metric_b,
        "from": f, "to": t, "n": n, "r": round(r, 3),
        "direction": "positive" if r > 0 else "negative",
    }


async def body_battery_drop_rate(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
) -> dict[str, Any]:
    """Median Body Battery drop rate (points/hour) over the window.

    Body battery declines during waking hours by design. The signal isn't
    that it drops — it's HOW FAST. This function computes per-day slope
    inside a local-time window `[hour_start, hour_end)` (or the full day
    if hours are omitted), then takes the median across days.

    Positive rate = gain (charging), negative = drain. The typical
    daytime hour will show a negative number; the question is how negative.

    Per-day calc:
      slope = (last_value - first_value) / hours_in_window

    The response also includes the rates list so the caller can see how
    consistent the pattern is across days.
    """
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, "body_battery", f, t)

    if hour_start is not None or hour_end is not None:
        if hour_start is None or hour_end is None:
            return {"error": "both hour_start and hour_end required (or neither)"}
        if not (0 <= hour_start < 24 and 0 < hour_end <= 24 and hour_start < hour_end):
            return {"error": "invalid_hours"}
        pairs = [
            (ts, v) for ts, v in pairs
            if (h := _hour_of(ts)) is not None and hour_start <= h < hour_end
        ]

    # Group by calendar day so each day yields one slope.
    by_day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ts, v in pairs:
        by_day[ts[:10]].append((ts, v))

    daily_rates: list[dict[str, Any]] = []
    rates: list[float] = []
    drops: list[float] = []
    for d in sorted(by_day.keys()):
        rows = sorted(by_day[d], key=lambda r: r[0])
        if len(rows) < 2:
            continue
        first_ts, first_v = rows[0]
        last_ts, last_v = rows[-1]
        try:
            duration_h = (
                datetime.fromisoformat(last_ts) - datetime.fromisoformat(first_ts)
            ).total_seconds() / 3600.0
        except ValueError:
            continue
        if duration_h <= 0:
            continue
        drop = first_v - last_v  # positive = drain in points
        rate_pts_per_hour = -drop / duration_h  # negative slope on drain
        daily_rates.append({
            "date": d,
            "first_value": round(first_v, 1),
            "last_value": round(last_v, 1),
            "drop_points": round(drop, 1),
            "duration_hours": round(duration_h, 2),
            "rate_points_per_hour": round(rate_pts_per_hour, 2),
        })
        rates.append(rate_pts_per_hour)
        drops.append(drop)

    n = len(rates)
    if n == 0:
        return {
            "from": f, "to": t,
            "hour_start": hour_start, "hour_end": hour_end,
            "n_days": 0, "low_confidence": True,
            "median_rate_points_per_hour": None,
            "median_drop_points": None,
            "daily": [],
        }

    return {
        "from": f, "to": t,
        "hour_start": hour_start, "hour_end": hour_end,
        "n_days": n,
        "low_confidence": n < 5,
        # Median slope: typically negative; how negative tells you "how
        # drastic" the drain is at this time of day for this user.
        "median_rate_points_per_hour": round(statistics.median(rates), 2),
        "median_drop_points": round(statistics.median(drops), 2),
        "min_rate_points_per_hour": round(min(rates), 2),  # most extreme drain
        "max_rate_points_per_hour": round(max(rates), 2),  # mildest / most charging
        "daily": daily_rates[-30:],  # cap returned detail
    }


async def body_battery_hourly_deltas(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """For each hour 0-23, the median net change (points) within that hour.

    Computed per-day: for hour H on day D, take the first and last BB
    reading inside [H:00, H+1:00) and record `last - first`. Negative =
    typical drain hour, positive = typical recovery hour.

    Used to spot recurring "every weekday at 14:00 you drain 12 points"
    patterns without the LLM having to compose it from raw samples.
    """
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, "body_battery", f, t)

    # Bucket by (date, hour).
    by_dh: dict[tuple[str, int], list[tuple[str, float]]] = defaultdict(list)
    for ts, v in pairs:
        h = _hour_of(ts)
        if h is None:
            continue
        by_dh[(ts[:10], h)].append((ts, v))

    # For each hour 0..23, collect per-day deltas.
    by_hour: dict[int, list[float]] = defaultdict(list)
    for (_day, hr), rows in by_dh.items():
        rows.sort(key=lambda r: r[0])
        if len(rows) < 2:
            continue
        delta = rows[-1][1] - rows[0][1]  # last - first
        by_hour[hr].append(delta)

    hours: dict[int, dict[str, Any]] = {}
    for h in range(24):
        vals = by_hour.get(h, [])
        hours[h] = {
            "n_days": len(vals),
            "median_delta": round(statistics.median(vals), 2) if vals else None,
            "min_delta": round(min(vals), 2) if vals else None,
            "max_delta": round(max(vals), 2) if vals else None,
        }
    return {"from": f, "to": t, "hours": hours}


async def stress_burden_by_zone(
    session: AsyncSession,
    from_iso: str | None = None,
    to_iso: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
) -> dict[str, Any]:
    """Percentage of recorded time in each Garmin stress zone over [from, to].

    Stress zones (Garmin's standard banding on a 0-100 score):
      - rest:   0-25
      - low:    26-50
      - medium: 51-75
      - high:   76-100

    More informative than `stats_for_metric("stress")` average. A flat 60 for
    4 hours and 0 for 3.5h + 95 for 30 min produce the same mean, but very
    different physiological pictures.

    Optional `hour_start`/`hour_end` restrict to a local-time window
    `[hour_start, hour_end)` — useful for "how stressful are my afternoons
    typically?" type questions.

    Reads from `metric_samples` (intra-day stress readings, ~1 per 3 min).
    """
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, "stress", f, t)

    if hour_start is not None or hour_end is not None:
        if hour_start is None or hour_end is None:
            return {"error": "both hour_start and hour_end required (or neither)"}
        if not (0 <= hour_start < 24 and 0 < hour_end <= 24 and hour_start < hour_end):
            return {"error": "invalid_hours"}
        pairs = [
            (ts, v) for ts, v in pairs
            if (h := _hour_of(ts)) is not None and hour_start <= h < hour_end
        ]

    n = len(pairs)
    if n == 0:
        return {
            "from": f, "to": t,
            "hour_start": hour_start, "hour_end": hour_end,
            "n": 0, "low_confidence": True,
            "zones": None, "burden_pct": None,
        }

    rest_n = sum(1 for _, v in pairs if v <= 25)
    low_n = sum(1 for _, v in pairs if 25 < v <= 50)
    med_n = sum(1 for _, v in pairs if 50 < v <= 75)
    high_n = sum(1 for _, v in pairs if v > 75)

    def pct(c: int) -> float:
        return round(c / n * 100.0, 1)

    # ~100 samples ≈ 5 hours of measurement; below that the breakdown is noisy.
    return {
        "from": f, "to": t,
        "hour_start": hour_start, "hour_end": hour_end,
        "n": n,
        "low_confidence": n < 100,
        "zones": {
            "rest":   {"pct": pct(rest_n), "n": rest_n,  "range": "0-25"},
            "low":    {"pct": pct(low_n),  "n": low_n,   "range": "26-50"},
            "medium": {"pct": pct(med_n),  "n": med_n,   "range": "51-75"},
            "high":   {"pct": pct(high_n), "n": high_n,  "range": "76-100"},
        },
        # "burden" = time outside resting state. The single most useful
        # summary number for physiological load.
        "burden_pct": pct(med_n + high_n),
    }


async def time_of_day_distribution(
    session: AsyncSession,
    name: str,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> dict[str, Any]:
    """Hourly buckets `{0..23: {median, n}}` for an intra-day metric."""
    if not _is_sample(name):
        return {
            "error": "not_intra_day",
            "name": name,
            "message": (
                f"`{name}` is a daily aggregate; time_of_day_distribution only "
                f"applies to intra-day metrics: {sorted(SAMPLE_METRIC_NAMES)}."
            ),
        }
    f = _normalize_from(from_iso)
    t = _normalize_to(to_iso)
    pairs = await _fetch_values_with_ts(session, name, f, t)
    buckets: dict[int, list[float]] = defaultdict(list)
    for ts, v in pairs:
        h = _hour_of(ts)
        if h is not None:
            buckets[h].append(v)
    hours: dict[int, dict[str, Any]] = {}
    for h in range(24):
        vals = buckets.get(h, [])
        hours[h] = {
            "n": len(vals),
            "median": round(statistics.median(vals), 3) if vals else None,
        }
    return {"name": name, "from": f, "to": t, "hours": hours}
