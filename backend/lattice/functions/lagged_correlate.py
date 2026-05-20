"""Lagged cross-correlation between two daily metrics.

Identifies whether metric B responds to metric A with a time delay —
e.g. 'yesterday's stress predicts today's HRV drop' (lag = -1 on stress).

Lag convention: positive lag means A leads B (A at day t vs B at day t+lag).
A peak at lag=+1 means 'A today predicts B tomorrow'.
A peak at lag=-1 means 'A yesterday predicts B today'.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import sqrt
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import Metric


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den_a = sqrt(sum((x - mx) ** 2 for x in xs))
    den_b = sqrt(sum((y - my) ** 2 for y in ys))
    if den_a == 0 or den_b == 0:
        return None
    return num / (den_a * den_b)


async def compute_lagged_correlation(
    session: AsyncSession,
    *,
    metric_a: str,
    metric_b: str,
    max_lag: int = 7,
    days: int = 90,
) -> dict[str, Any]:
    """Compute Pearson r between metric_a and metric_b at lags -max_lag..+max_lag.

    Returns:
      metric_a           name of leading metric
      metric_b           name of lagged metric
      lags               list of {lag, r, n} ordered by lag
      peak_lag           lag with highest |r|
      peak_r             r at peak_lag
      peak_n             n at peak_lag
      days_analysed      data window used
      interpretation     human-readable finding
      low_confidence     true when peak_n < 10
    """
    tz = settings.timezone
    zone = ZoneInfo(tz)
    today = datetime.now(UTC).astimezone(zone).date()
    start = today - timedelta(days=days - 1)
    start_iso = start.isoformat()

    stmt = select(Metric).where(
        Metric.metric_name.in_([metric_a, metric_b]),
        Metric.timestamp >= start_iso,
    ).order_by(Metric.timestamp.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    a_by_date: dict[str, float] = {}
    b_by_date: dict[str, float] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(r.timestamp).astimezone(zone).date().isoformat()
        except (ValueError, TypeError):
            continue
        if r.metric_name == metric_a:
            a_by_date[d] = float(r.value)
        else:
            b_by_date[d] = float(r.value)

    all_dates = sorted(set(a_by_date) | set(b_by_date))
    date_idx = {d: i for i, d in enumerate(all_dates)}

    a_vals = [a_by_date.get(d) for d in all_dates]
    b_vals = [b_by_date.get(d) for d in all_dates]

    lag_results: list[dict[str, Any]] = []
    for lag in range(-max_lag, max_lag + 1):
        pairs_a: list[float] = []
        pairs_b: list[float] = []
        for i, d in enumerate(all_dates):
            va = a_vals[i]
            if va is None:
                continue
            # B at date = d + lag days
            target_d_obj = datetime.fromisoformat(d).date() + timedelta(days=lag)
            target_d = target_d_obj.isoformat()
            j = date_idx.get(target_d)
            if j is None:
                continue
            vb = b_vals[j]
            if vb is None:
                continue
            pairs_a.append(va)
            pairs_b.append(vb)

        r_val = _pearson(pairs_a, pairs_b)
        lag_results.append({
            "lag": lag,
            "r": round(r_val, 3) if r_val is not None else None,
            "n": len(pairs_a),
        })

    # Find peak lag (highest |r| with n >= 5)
    best = max(
        (x for x in lag_results if x["r"] is not None and x["n"] >= 5),
        key=lambda x: abs(x["r"]),
        default=None,
    )

    if best is None:
        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "lags": lag_results,
            "peak_lag": None,
            "peak_r": None,
            "peak_n": 0,
            "days_analysed": days,
            "interpretation": "insufficient data for lagged correlation",
            "low_confidence": True,
        }

    lag = best["lag"]
    r = best["r"]
    n = best["n"]

    if lag == 0:
        lag_desc = "same day"
    elif lag > 0:
        lag_desc = f"{lag} day{'s' if lag > 1 else ''} later"
    else:
        lag_desc = f"{abs(lag)} day{'s' if abs(lag) > 1 else ''} earlier"

    direction = "positively" if r > 0 else "inversely"
    strength = "strongly" if abs(r) >= 0.5 else "moderately" if abs(r) >= 0.3 else "weakly"
    interp = (
        f"{metric_a} {strength} {direction} correlates with {metric_b} at lag {lag:+d} "
        f"(r={r:.2f}, n={n}): {metric_b} peaks {lag_desc} relative to {metric_a}"
    )

    if abs(r) < 0.3:
        interp = f"no meaningful lagged correlation found between {metric_a} and {metric_b} (peak |r|={abs(r):.2f})"

    return {
        "metric_a": metric_a,
        "metric_b": metric_b,
        "lags": lag_results,
        "peak_lag": lag,
        "peak_r": r,
        "peak_n": n,
        "days_analysed": days,
        "interpretation": interp,
        "low_confidence": n < 10,
    }


__all__ = ["compute_lagged_correlation"]
