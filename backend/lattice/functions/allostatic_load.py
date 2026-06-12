"""Allostatic Load Index (ALI).

Allostatic load quantifies cumulative physiological stress across multiple
biomarker systems. Each marker is scored 0 (healthy) or 1 (stressed) based
on whether the recent value falls in an adverse quartile relative to the
user's own trailing distribution — personalised, not population-based.

Markers used (P1-6: `readiness_score` dropped — it is itself derived from
HRV/RHR/sleep/body-battery/stress, so including it double-counts each
underlying system. The published McEwen/Seeman framework uses independent
physiological systems):
  HRV           hrv_overnight_avg      — low = stressed (bottom quartile)
  Resting HR    resting_hr             — high = stressed (top quartile)
  Sleep quality sleep_score            — low = stressed (bottom quartile)
  Sleep duration sleep_duration_min    — low = stressed (<6h)
  Stress        stress_avg             — high = stressed (top quartile)
  Body battery  body_battery_start     — low = stressed (bottom quartile)
  VO2max        vo2_max                — low = stressed (bottom quartile)

Score 0-7: 0-1 = low load, 2-3 = moderate, 4-5 = high, 6+ = very high.

A baseline-relative quartile flag is informative but, by construction, ~25 %
of any normal week's days fall in the user's own adverse quartile — so even
a healthy week can score 1-2/7. The interpretation text reflects this:
moderate is described as "within normal variation", not as warning.

References: McEwen (1998, 2003), Seeman et al. (2004) framework adapted
for wearable biomarker data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric

_BASELINE_DAYS = 90

_MARKERS: list[dict[str, Any]] = [
    {"name": "hrv_overnight_avg",  "direction": "low_bad",  "label": "HRV"},
    {"name": "resting_hr",         "direction": "high_bad", "label": "Resting HR"},
    {"name": "sleep_score",        "direction": "low_bad",  "label": "Sleep quality"},
    {"name": "sleep_duration_min", "direction": "low_bad",  "label": "Sleep duration",
     "hard_threshold": 360.0},  # < 6h is always stressed
    {"name": "stress_avg",         "direction": "high_bad", "label": "Stress"},
    {"name": "body_battery_start", "direction": "low_bad",  "label": "Body battery"},
    {"name": "vo2_max",            "direction": "low_bad",  "label": "VO2max"},
]


def _quartile(vals: list[float], q: float) -> float:
    """Linear interpolation quantile."""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return 0.0
    pos = q * (n - 1)
    lo = int(pos)
    hi = lo + 1
    if hi >= n:
        return s[-1]
    frac = pos - lo
    return s[lo] + frac * (s[hi] - s[lo])


async def compute_allostatic_load(
    session: AsyncSession,
    *,
    baseline_days: int = _BASELINE_DAYS,
    recent_days: int = 7,
) -> dict[str, Any]:
    """Compute personalised Allostatic Load Index from the last `recent_days` average
    vs the `baseline_days` distribution.

    Returns:
      score            0–8 integer ALI
      max_score        number of markers with data
      category         'low' | 'moderate' | 'high' | 'very high'
      components       [{label, marker, recent_mean, baseline_q25/q75, flag, direction}]
      interpretation   human-readable assessment
      low_confidence   true when fewer than 4 markers had data
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    baseline_start = (today - timedelta(days=baseline_days - 1)).isoformat()

    all_names = [m["name"] for m in _MARKERS]
    stmt = select(Metric).where(
        Metric.metric_name.in_(all_names),
        Metric.timestamp >= baseline_start,
    ).order_by(Metric.timestamp.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    by_metric: dict[str, list[tuple[str, float]]] = {n: [] for n in all_names}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date().isoformat()
        except (ValueError, TypeError):
            continue
        by_metric[r.metric_name].append((d, float(r.value)))

    recent_cutoff = (today - timedelta(days=recent_days - 1)).isoformat()

    components: list[dict[str, Any]] = []
    score = 0
    markers_with_data = 0

    for m_def in _MARKERS:
        name = m_def["name"]
        direction = m_def["direction"]
        label = m_def["label"]
        data = by_metric[name]

        if len(data) < 5:
            continue

        baseline_vals = [v for (d, v) in data]
        recent_vals = [v for (d, v) in data if d >= recent_cutoff]

        if not recent_vals:
            continue

        markers_with_data += 1
        recent_mean = sum(recent_vals) / len(recent_vals)
        q25 = _quartile(baseline_vals, 0.25)
        q75 = _quartile(baseline_vals, 0.75)

        # Flag as stressed:
        # low_bad: recent mean in bottom quartile (< Q25)
        # high_bad: recent mean in top quartile (> Q75)
        hard = m_def.get("hard_threshold")
        if direction == "low_bad":
            flagged = recent_mean < q25 or (hard is not None and recent_mean < hard)
        else:
            flagged = recent_mean > q75

        if flagged:
            score += 1

        components.append({
            "label": label,
            "marker": name,
            "recent_mean": round(recent_mean, 1),
            "baseline_q25": round(q25, 1),
            "baseline_q75": round(q75, 1),
            "flag": flagged,
            "direction": direction,
        })

    # Category — interpretation accounts for baseline-relative scoring.
    # ~25 % of normal days fall in the user's own adverse quartile, so a
    # healthy week typically scores 1–2/7 even with no real strain.
    if score <= 2:
        category = "low"
        cat_text = (
            "allostatic load within normal variation — systems well-regulated"
        )
    elif score <= 4:
        category = "moderate"
        cat_text = (
            "elevated allostatic load — a few systems trending below baseline"
        )
    elif score <= 5:
        category = "high"
        cat_text = "high allostatic load — multiple systems under stress"
    else:
        category = "very high"
        cat_text = "very high allostatic load — significant physiological wear"

    flagged_labels = [c["label"] for c in components if c["flag"]]
    if flagged_labels:
        interp = f"{cat_text}. Stressed markers: {', '.join(flagged_labels)}."
    else:
        interp = cat_text + "."

    return {
        "score": score,
        "max_score": markers_with_data,
        "category": category,
        "components": components,
        "interpretation": interp,
        "low_confidence": markers_with_data < 4,
    }


__all__ = ["compute_allostatic_load"]
