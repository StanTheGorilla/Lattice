"""Close the planning ↔ data loop.

For every active initiative that has a `target_metric` set, fetch the
current metric value and compute progress toward the target.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.baselines import compute_baseline, metric_on_date
from lattice.models import Area, Initiative

# Metrics where smaller is better (used for progress direction).
_LOWER_IS_BETTER: frozenset[str] = frozenset({
    "resting_hr", "stress_avg", "sleep_awake_min", "restless_moments_count",
})


async def get_initiative_metrics(session: AsyncSession) -> dict[str, Any]:
    """Return progress data for all active initiatives that track a metric.

    Each item contains:
      initiative_id, initiative_title, area, target_metric, target_value,
      current_value, baseline_14d_mean, baseline_14d_n, progress_note
    """
    stmt = (
        select(Initiative, Area)
        .outerjoin(Area, Initiative.area_id == Area.id)
        .where(
            Initiative.status == "active",
            Initiative.target_metric.is_not(None),
        )
        .order_by(Area.sort_order.asc(), Initiative.created_at.desc())
    )
    rows = list((await session.execute(stmt)).all())

    if not rows:
        return {
            "count": 0,
            "items": [],
            "note": "no active initiatives with target_metric set",
        }

    tz = settings.timezone
    today = datetime.now(UTC).date()

    items = []
    for init, area in rows:
        metric_name = init.target_metric  # already checked .is_not(None)
        current_row = await metric_on_date(session, metric_name, today, tz)
        current = round(float(current_row.value), 2) if current_row else None
        baseline = await compute_baseline(session, metric_name, days=14, before=today, tz=tz)

        progress_note: str | None = None
        if current is not None and init.target_value is not None:
            lower_better = metric_name in _LOWER_IS_BETTER
            target = init.target_value
            if lower_better:
                if current <= target:
                    progress_note = f"target met ({current} ≤ {target})"
                else:
                    progress_note = f"{current - target:.1f} above target {target}"
            else:
                if current >= target:
                    progress_note = f"target met ({current} ≥ {target})"
                else:
                    pct = current / target * 100 if target else None
                    progress_note = (
                        f"{target - current:.1f} below target {target}"
                        + (f" ({pct:.0f}%)" if pct is not None else "")
                    )

        items.append({
            "initiative_id": init.id,
            "initiative_title": init.title,
            "area": area.name if area else None,
            "target_metric": metric_name,
            "target_value": init.target_value,
            "target_date": init.target_date,
            "current_value": current,
            "baseline_14d_mean": (
                round(baseline.mean, 2) if baseline.mean is not None else None
            ),
            "baseline_14d_n": baseline.n,
            "progress_note": progress_note,
        })

    return {"count": len(items), "items": items}


__all__ = ["get_initiative_metrics"]
