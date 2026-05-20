"""Sleep architecture analysis.

Computes scientifically grounded sleep architecture metrics from Garmin
sleep-stage data (sleep_stages table):

1. REM latency — time from sleep onset to first REM episode.
   Normal: 70-120 min. Short (<70 min) may indicate depression/narcolepsy.
   Long (>120 min) suggests suppressed REM (alcohol, stress, fragmentation).

2. Deep-sleep front-loading ratio — fraction of total deep sleep occurring
   in the first third of the sleep period vs later.
   Normal: deep sleep is heavily front-loaded (Hobson 1989); ratio ~0.6+.
   Low ratio means deep sleep shifted toward morning — less restorative.

3. Sleep fragmentation index — number of wake/brief-arousal events per hour
   of sleep. Normal < 5/hour. Higher correlates with daytime fatigue.

4. REM cycles per night — number of discrete REM episodes.
   Normal: 4-6 per night. Fewer cycles = less REM (high stress, alcohol).

Sources: Rechtschaffen & Kales (1968), Hobson (1989), Walker (2017).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings

try:
    from lattice.models import SleepStage
    _HAS_SLEEP_STAGE = True
except ImportError:
    _HAS_SLEEP_STAGE = False


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


async def _fetch_nights(session: AsyncSession, start_iso: str, end_iso: str) -> dict[str, list[dict[str, Any]]]:
    """Return stages grouped by night_date."""
    if not _HAS_SLEEP_STAGE:
        return {}

    stmt = select(SleepStage).where(
        SleepStage.night_date >= start_iso,
        SleepStage.night_date <= end_iso,
    ).order_by(SleepStage.night_date.asc(), SleepStage.start.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    nights: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        seg = {
            "stage": r.stage,
            "start": r.start,
            "end": r.end,
            "duration_min": float(r.duration_min),
        }
        nights.setdefault(r.night_date, []).append(seg)
    return nights


def _parse_minutes(ts: str) -> float | None:
    """Convert ISO 8601 timestamp to minutes-since-midnight."""
    try:
        dt = datetime.fromisoformat(ts)
        return dt.hour * 60 + dt.minute + dt.second / 60.0
    except (ValueError, TypeError):
        return None


def _analyse_night(segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Analyse one night's stage segments. Returns per-night metrics or None."""
    if not segments:
        return None

    # Sort by start time
    segs = sorted(segments, key=lambda s: s["start"])

    # Find sleep onset = first non-wake segment
    sleep_onset_ts: str | None = None
    for s in segs:
        if s["stage"] not in ("awake", "unmeasured"):
            sleep_onset_ts = s["start"]
            break

    if sleep_onset_ts is None:
        return None

    # Total sleep duration (non-wake minutes)
    total_sleep_min = sum(s["duration_min"] for s in segs if s["stage"] not in ("awake", "unmeasured"))
    if total_sleep_min < 60:
        return None

    # Sleep period duration (last end - first non-wake start)
    sleep_end_ts = segs[-1]["end"]
    try:
        onset_dt = datetime.fromisoformat(sleep_onset_ts)
        end_dt = datetime.fromisoformat(sleep_end_ts)
        period_min = (end_dt - onset_dt).total_seconds() / 60.0
    except (ValueError, TypeError):
        return None

    if period_min <= 0:
        return None

    # 1. REM latency: minutes from sleep onset to first REM
    rem_latency: float | None = None
    for s in segs:
        if s["stage"] == "rem" and s["start"] >= sleep_onset_ts:
            try:
                seg_dt = datetime.fromisoformat(s["start"])
                rem_latency = (seg_dt - onset_dt).total_seconds() / 60.0
            except (ValueError, TypeError):
                pass
            break

    # 2. Deep sleep front-loading: compare deep in first vs second half of sleep period
    half = period_min / 2.0
    deep_first_half = 0.0
    deep_second_half = 0.0
    total_deep = 0.0
    for s in segs:
        if s["stage"] != "deep":
            continue
        total_deep += s["duration_min"]
        try:
            seg_offset = (datetime.fromisoformat(s["start"]) - onset_dt).total_seconds() / 60.0
        except (ValueError, TypeError):
            continue
        if seg_offset < half:
            deep_first_half += s["duration_min"]
        else:
            deep_second_half += s["duration_min"]

    front_load_ratio: float | None = None
    if total_deep > 0:
        front_load_ratio = round(deep_first_half / total_deep, 3)

    # 3. Fragmentation index: wake events per hour of sleep
    wake_events = sum(1 for s in segs if s["stage"] == "awake")
    frag_index = round(wake_events / (total_sleep_min / 60.0), 2) if total_sleep_min > 0 else None

    # 4. REM cycles: number of discrete REM episodes
    rem_cycles = 0
    in_rem = False
    for s in segs:
        if s["stage"] == "rem" and not in_rem:
            rem_cycles += 1
            in_rem = True
        elif s["stage"] != "rem":
            in_rem = False

    return {
        "rem_latency_min": round(rem_latency, 1) if rem_latency is not None else None,
        "deep_frontload_ratio": front_load_ratio,
        "fragmentation_index": frag_index,
        "rem_cycles": rem_cycles,
        "total_sleep_min": round(total_sleep_min, 1),
        "deep_min": round(total_deep, 1),
    }


async def compute_sleep_architecture(
    session: AsyncSession,
    *,
    days: int = 14,
) -> dict[str, Any]:
    """Compute sleep architecture metrics over the last `days` nights.

    Returns:
      n_nights                 nights with usable stage data
      median_rem_latency_min   typical REM onset latency
      median_deep_frontload    typical deep-sleep front-loading ratio (0-1)
      median_fragmentation     typical wake events per hour
      median_rem_cycles        typical REM cycles per night
      per_night                list of nightly breakdowns
      interpretation           multi-point clinical assessment
      low_confidence           true when n_nights < 5
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    start = today - timedelta(days=days - 1)

    nights_data = await _fetch_nights(session, start.isoformat(), today.isoformat())

    per_night: list[dict[str, Any]] = []
    for night_date, segments in sorted(nights_data.items()):
        result = _analyse_night(segments)
        if result is not None:
            result["night_date"] = night_date
            per_night.append(result)

    n = len(per_night)

    if n == 0:
        return {
            "n_nights": 0,
            "median_rem_latency_min": None,
            "median_deep_frontload": None,
            "median_fragmentation": None,
            "median_rem_cycles": None,
            "per_night": [],
            "interpretation": "no sleep stage data available",
            "low_confidence": True,
        }

    rem_lats = [p["rem_latency_min"] for p in per_night if p["rem_latency_min"] is not None]
    frontloads = [p["deep_frontload_ratio"] for p in per_night if p["deep_frontload_ratio"] is not None]
    frags = [p["fragmentation_index"] for p in per_night if p["fragmentation_index"] is not None]
    cycles = [float(p["rem_cycles"]) for p in per_night]

    med_rem = _median(rem_lats)
    med_fl = _median(frontloads)
    med_frag = _median(frags)
    med_cycles = _median(cycles)

    # Interpretation
    findings: list[str] = []

    if med_rem is not None:
        if med_rem < 60:
            findings.append(f"Short REM latency ({med_rem:.0f} min) — may reflect pressure for REM, depression risk or sleep deprivation")
        elif med_rem > 120:
            findings.append(f"Long REM latency ({med_rem:.0f} min) — REM suppression likely (alcohol, high cortisol, medication)")
        else:
            findings.append(f"REM latency normal ({med_rem:.0f} min, target 70-120 min)")

    if med_fl is not None:
        if med_fl < 0.5:
            findings.append(f"Poor deep-sleep front-loading ({med_fl:.0%}) — deep sleep shifted toward morning, less restorative")
        elif med_fl >= 0.65:
            findings.append(f"Good deep-sleep front-loading ({med_fl:.0%}) — deep sleep concentrated in early sleep, normal")
        else:
            findings.append(f"Moderate deep-sleep front-loading ({med_fl:.0%})")

    if med_frag is not None:
        if med_frag > 8:
            findings.append(f"High sleep fragmentation ({med_frag:.1f} wake events/h) — clinically significant disruption")
        elif med_frag > 5:
            findings.append(f"Moderate sleep fragmentation ({med_frag:.1f} wake events/h)")
        else:
            findings.append(f"Low sleep fragmentation ({med_frag:.1f} wake events/h) — good consolidation")

    if med_cycles is not None:
        if med_cycles < 4:
            findings.append(f"Low REM cycle count ({med_cycles:.1f}/night, normal 4-6) — REM suppression or short sleep")
        else:
            findings.append(f"REM cycles: {med_cycles:.1f}/night (normal)")

    interp = "; ".join(findings) if findings else "insufficient data for architecture assessment"

    return {
        "n_nights": n,
        "median_rem_latency_min": round(med_rem, 1) if med_rem is not None else None,
        "median_deep_frontload": round(med_fl, 3) if med_fl is not None else None,
        "median_fragmentation": round(med_frag, 2) if med_frag is not None else None,
        "median_rem_cycles": round(med_cycles, 1) if med_cycles is not None else None,
        "per_night": per_night,
        "interpretation": interp,
        "low_confidence": n < 5,
    }


__all__ = ["compute_sleep_architecture"]
