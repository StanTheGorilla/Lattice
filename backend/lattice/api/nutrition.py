"""Nutrition endpoints — estimate + daily summary."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.functions.nutrition import estimate_nutrition
from lattice.models import Entry

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/nutrition",
    tags=["nutrition"],
    dependencies=[Depends(require_auth)],
)


class EstimateRequest(BaseModel):
    description: str
    grams: float | None = None


@router.post("/estimate")
async def estimate_endpoint(payload: EstimateRequest) -> dict[str, Any]:
    """Estimate macronutrients for a food description (does not save anything)."""
    est = await estimate_nutrition(payload.description, payload.grams)
    if est is None:
        return {
            "error": "estimation_failed",
            "message": "Could not estimate nutrition (API unavailable or key missing)",
        }
    return est.to_dict()


@router.get("/daily")
async def daily_nutrition(
    date_: str | None = Query(default=None, alias="date"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return nutrition totals for all food entries logged on a given date."""
    tz = ZoneInfo(settings.timezone)
    if date_:
        try:
            target_date = date.fromisoformat(date_)
        except ValueError:
            target_date = datetime.now(UTC).astimezone(tz).date()
    else:
        target_date = datetime.now(UTC).astimezone(tz).date()

    day_start = f"{target_date.isoformat()}T00:00:00"
    day_end = f"{target_date.isoformat()}T23:59:59"

    stmt = (
        select(Entry)
        .where(
            Entry.type == "food",
            Entry.timestamp >= day_start,
            Entry.timestamp <= day_end,
        )
        .order_by(Entry.timestamp.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    _KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g")
    totals: dict[str, float] = {k: 0.0 for k in _KEYS}
    meals: list[dict[str, Any]] = []

    for row in rows:
        try:
            data = json.loads(row.data)
        except Exception:
            continue
        nutrition = data.get("nutrition")
        meals.append({
            "id": row.id,
            "timestamp": row.timestamp,
            "description": data.get("description", ""),
            "meal_type": data.get("meal_type"),
            "grams": data.get("grams"),
            "nutrition": nutrition,
        })
        if nutrition:
            for k in _KEYS:
                totals[k] += float(nutrition.get(k) or 0)

    has_nutrition = any(m["nutrition"] is not None for m in meals)
    return {
        "date": target_date.isoformat(),
        "meals_logged": len(meals),
        "has_nutrition": has_nutrition,
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "meals": meals,
    }


@router.get("/history")
async def nutrition_history(
    days: int = Query(default=30, ge=1, le=180),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return daily macro totals for the last N days (only days with ≥1 nutrition entry)."""
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(UTC).astimezone(tz).date()

    _KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g")
    from_date = today - timedelta(days=days - 1)
    stmt = (
        select(Entry)
        .where(
            Entry.type == "food",
            Entry.timestamp >= f"{from_date.isoformat()}T00:00:00",
            Entry.timestamp <= f"{today.isoformat()}T23:59:59",
        )
        .order_by(Entry.timestamp.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    by_day: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            data = json.loads(row.data)
        except Exception:
            continue
        nutrition = data.get("nutrition")
        if not nutrition:
            continue
        day = row.timestamp[:10]
        if day not in by_day:
            by_day[day] = {k: 0.0 for k in _KEYS}
        for k in _KEYS:
            by_day[day][k] += float(nutrition.get(k) or 0)

    series = [
        {"date": d, **{k: round(v, 1) for k, v in totals.items()}}
        for d, totals in sorted(by_day.items())
    ]
    return {"days": days, "series": series}


__all__ = ["router"]
