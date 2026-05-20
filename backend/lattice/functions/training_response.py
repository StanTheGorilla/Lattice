"""Training load response curve (Acute:Chronic Workload Ratio).

Implements the Banister impulse-response (TRIMP) framework adapted for
Garmin data. Uses exponentially weighted moving averages to track:

  Acute Training Load (ATL)   — 7-day EWMA of daily load (fatigue)
  Chronic Training Load (CTL) — 28-day EWMA of daily load (fitness)
  A:C ratio                   — ATL / CTL

Interpretation:
  < 0.8  — undertraining / detraining
  0.8-1.3 — optimal range (sweet spot)
  1.3-1.5 — caution zone
  > 1.5  — injury risk zone (Foster et al. 1998, Gabbett 2016)

Training load proxy used:
  If aerobic_training_effect is available: use it directly (scale 1-5).
  Otherwise: use (duration_min / 60) * avg_hr / max_hr as a crude TRIMP proxy.
  Falls back to step count as a last resort (scaled to 0-5 range).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from math import exp
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric

_ATL_DAYS = 7    # acute window (exponential half-life equivalent)
_CTL_DAYS = 28   # chronic window

# EWMA decay constants: alpha = 2/(n+1)
_ATL_ALPHA = 2.0 / (_ATL_DAYS + 1)
_CTL_ALPHA = 2.0 / (_CTL_DAYS + 1)

_LOAD_METRICS = [
    "aerobic_training_effect",
    "anaerobic_training_effect",
    "steps",
]

_RISK_ZONES = [
    (0.0, 0.8,  "undertraining", "load below fitness-building threshold"),
    (0.8, 1.3,  "optimal",       "sweet spot — building fitness with manageable fatigue"),
    (1.3, 1.5,  "caution",       "approaching overreaching — monitor recovery closely"),
    (1.5, 99.0, "high_risk",     "injury / overtraining risk zone (Gabbett 2016)"),
]


def _ewma(series: list[float], alpha: float) -> list[float]:
    """Compute EWMA for a time-ordered series."""
    if not series:
        return []
    result = [series[0]]
    for v in series[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _zone(ratio: float) -> tuple[str, str]:
    for lo, hi, name, desc in _RISK_ZONES:
        if lo <= ratio < hi:
            return name, desc
    return _RISK_ZONES[-1][2], _RISK_ZONES[-1][3]


async def compute_training_load_response(
    session: AsyncSession,
    *,
    days: int = 60,
) -> dict[str, Any]:
    """Compute ATL, CTL, and A:C ratio over the last `days` days.

    Returns:
      current_atl          current acute training load (EWMA)
      current_ctl          current chronic training load (EWMA)
      ac_ratio             ATL / CTL (None if CTL=0)
      risk_zone            'undertraining' | 'optimal' | 'caution' | 'high_risk'
      risk_description     plain-text zone description
      trend                'increasing' | 'decreasing' | 'stable' (7-day ratio trend)
      daily_series         [{date, load, atl, ctl, ac_ratio}] for charting
      load_metric_used     which metric was used as load proxy
      n_days_with_load     days that had non-zero load
      interpretation       human-readable assessment
      low_confidence       true when n_days_with_load < 10
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    # Pull extra history for EWMA warm-up (28 days before window)
    fetch_start = today - timedelta(days=days + _CTL_DAYS - 1)

    stmt = select(Metric).where(
        Metric.metric_name.in_(_LOAD_METRICS),
        Metric.timestamp >= fetch_start.isoformat(),
    ).order_by(Metric.timestamp.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    # Group by date, prefer aerobic_training_effect > anaerobic > steps
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date().isoformat()
        except (ValueError, TypeError):
            continue
        by_date.setdefault(d, {})[r.metric_name] = float(r.value)

    # Determine load proxy
    has_te = any("aerobic_training_effect" in v for v in by_date.values())
    has_anaerobic = any("anaerobic_training_effect" in v for v in by_date.values())
    has_steps = any("steps" in v for v in by_date.values())

    if has_te:
        load_metric = "aerobic_training_effect"

        def load_fn(d: dict[str, float]) -> float:
            return d.get("aerobic_training_effect", 0.0)
    elif has_anaerobic:
        load_metric = "anaerobic_training_effect"

        def load_fn(d: dict[str, float]) -> float:
            return d.get("anaerobic_training_effect", 0.0)
    elif has_steps:
        load_metric = "steps (scaled)"

        def load_fn(d: dict[str, float]) -> float:
            # Scale steps to 0-5 range: ~10k steps = 1.0 TE
            return min(5.0, d.get("steps", 0.0) / 10000.0)
    else:
        return {
            "current_atl": None,
            "current_ctl": None,
            "ac_ratio": None,
            "risk_zone": None,
            "risk_description": "no training load data found",
            "trend": None,
            "daily_series": [],
            "load_metric_used": "none",
            "n_days_with_load": 0,
            "interpretation": "no training load metrics available",
            "low_confidence": True,
        }

    # Build daily load series (fill 0 for missing days)
    all_dates: list[str] = []
    d_iter = fetch_start
    while d_iter <= today:
        all_dates.append(d_iter.isoformat())
        d_iter += timedelta(days=1)

    loads = [load_fn(by_date.get(d, {})) for d in all_dates]

    # Compute EWMA
    atl_series = _ewma(loads, _ATL_ALPHA)
    ctl_series = _ewma(loads, _CTL_ALPHA)

    # Trim to the requested window
    window_start = today - timedelta(days=days - 1)
    out_series: list[dict[str, Any]] = []
    for i, d in enumerate(all_dates):
        if d < window_start.isoformat():
            continue
        atl = atl_series[i]
        ctl = ctl_series[i]
        ratio = round(atl / ctl, 3) if ctl > 0 else None
        out_series.append({
            "date": d,
            "load": round(loads[i], 2),
            "atl": round(atl, 3),
            "ctl": round(ctl, 3),
            "ac_ratio": ratio,
        })

    current_atl = atl_series[-1] if atl_series else 0.0
    current_ctl = ctl_series[-1] if ctl_series else 0.0
    current_ratio = current_atl / current_ctl if current_ctl > 0 else None

    # 7-day trend of A:C ratio
    trend_series = [s["ac_ratio"] for s in out_series[-7:] if s["ac_ratio"] is not None]
    if len(trend_series) >= 4:
        first_half = sum(trend_series[:len(trend_series) // 2]) / (len(trend_series) // 2)
        second_half = sum(trend_series[len(trend_series) // 2:]) / (len(trend_series) - len(trend_series) // 2)
        delta = second_half - first_half
        if delta > 0.05:
            trend = "increasing"
        elif delta < -0.05:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    n_load_days = sum(1 for v in loads[-days:] if v > 0)

    zone_name, zone_desc = _zone(current_ratio) if current_ratio is not None else ("unknown", "insufficient data")

    if current_ratio is not None:
        interp = (
            f"A:C ratio {current_ratio:.2f} → {zone_name} zone ({zone_desc}). "
            f"ATL={current_atl:.2f}, CTL={current_ctl:.2f}. "
            f"7-day trend: {trend}."
        )
        if zone_name == "high_risk":
            interp += " Reduce training intensity or add a recovery day."
        elif zone_name == "undertraining":
            interp += " Gradually increasing load would build fitness."
    else:
        interp = "Insufficient training load data for A:C ratio."

    return {
        "current_atl": round(current_atl, 3),
        "current_ctl": round(current_ctl, 3),
        "ac_ratio": round(current_ratio, 3) if current_ratio is not None else None,
        "risk_zone": zone_name,
        "risk_description": zone_desc,
        "trend": trend,
        "daily_series": out_series,
        "load_metric_used": load_metric,
        "n_days_with_load": n_load_days,
        "interpretation": interp,
        "low_confidence": n_load_days < 10,
    }


__all__ = ["compute_training_load_response"]
