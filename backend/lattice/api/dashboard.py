"""Dashboard card endpoints (Phase 2L-c).

Cards are created by the chat agent via `render_chart`. The web UI loads
them here — each GET resolves the stored data_source spec against current
metric data so charts always reflect the latest values.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.functions.baselines import metric_for_day_range
from lattice.models import DashboardCard
from lattice.schemas.dashboard import (
    CardMoveRequest,
    DashboardCardListResponse,
    DashboardCardOut,
    DataSourceLineBar,
    DataSourceTable,
    ResolvedLineBar,
    ResolvedTable,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(require_auth)],
)


def _short_date_label(d: date) -> str:
    """'May 23' style label for x-axes."""
    return d.strftime("%b %-d") if hasattr(d, "strftime") else str(d)


def _date_range(end: date, days: int) -> list[date]:
    """Inclusive list of [end-days+1, end]."""
    return [end - timedelta(days=days - 1 - i) for i in range(days)]


async def _resolve_line_bar(
    session: AsyncSession, spec: DataSourceLineBar, chart_type: str, tz: str,
) -> ResolvedLineBar:
    today = datetime.now(ZoneInfo(tz)).date()
    days_list = _date_range(today, spec.days)
    labels = [_short_date_label(d) for d in days_list]

    series_out: list[dict[str, Any]] = []
    for s in spec.series:
        if s.metric:
            rows = await metric_for_day_range(
                session, s.metric, days_list[0], days_list[-1], tz,
            )
            by_iso: dict[str, float] = {}
            for r in rows:
                day_key = r.timestamp[:10]  # 'YYYY-MM-DD'
                by_iso[day_key] = float(r.value)
            data: list[float | None] = [
                by_iso.get(d.isoformat()) for d in days_list
            ]
        elif s.value is not None:
            data = [float(s.value)] * len(days_list)
        else:
            data = [None] * len(days_list)
        item: dict[str, Any] = {"name": s.name, "data": data}
        if s.color:
            item["color"] = s.color
        series_out.append(item)

    return ResolvedLineBar(
        chart_type=chart_type,  # type: ignore[arg-type]
        labels=labels,
        series=series_out,
    )


async def _resolve_table(
    session: AsyncSession, spec: DataSourceTable, tz: str,
) -> ResolvedTable:
    today = datetime.now(ZoneInfo(tz)).date()
    days_list = _date_range(today, spec.days)

    # Pre-fetch each column.
    per_col: dict[str, dict[str, float]] = {}
    for col in spec.metric_columns:
        rows = await metric_for_day_range(
            session, col, days_list[0], days_list[-1], tz,
        )
        per_col[col] = {r.timestamp[:10]: float(r.value) for r in rows}

    columns = ["Date", *spec.metric_columns]
    table_rows: list[list[Any]] = []
    for d in days_list:
        row: list[Any] = [_short_date_label(d)]
        iso = d.isoformat()
        for col in spec.metric_columns:
            row.append(per_col[col].get(iso))
        table_rows.append(row)

    return ResolvedTable(chart_type="table", columns=columns, rows=table_rows)


async def _resolve_card(
    session: AsyncSession, card: DashboardCard,
) -> DashboardCardOut:
    spec_raw = json.loads(card.data_source)
    tz = settings.timezone
    if card.chart_type in ("line", "bar"):
        spec = DataSourceLineBar.model_validate(spec_raw)
        resolved: ResolvedLineBar | ResolvedTable = await _resolve_line_bar(
            session, spec, card.chart_type, tz,
        )
    elif card.chart_type == "table":
        spec_t = DataSourceTable.model_validate(spec_raw)
        resolved = await _resolve_table(session, spec_t, tz)
    else:
        raise HTTPException(
            500,
            detail={
                "error": "bad_chart_type",
                "message": f"unknown chart_type '{card.chart_type}'",
            },
        )

    return DashboardCardOut(
        id=card.id,
        title=card.title,
        chart_type=card.chart_type,  # type: ignore[arg-type]
        position=card.position,
        created_at=card.created_at,
        data_source=spec_raw,
        resolved=resolved,
    )


@router.get("/cards", response_model=DashboardCardListResponse)
async def list_cards(
    session: AsyncSession = Depends(get_session),
) -> DashboardCardListResponse:
    stmt = select(DashboardCard).order_by(
        DashboardCard.position.asc(), DashboardCard.id.asc(),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    items: list[DashboardCardOut] = []
    for r in rows:
        try:
            items.append(await _resolve_card(session, r))
        except Exception:  # noqa: BLE001
            logger.exception("dashboard card %d failed to resolve", r.id)
    return DashboardCardListResponse(items=items)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(
    card_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = (
        await session.execute(
            select(DashboardCard).where(DashboardCard.id == card_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": f"card {card_id} not found"},
        )
    await session.delete(row)
    await session.commit()


@router.patch("/cards/{card_id}/move", response_model=DashboardCardOut)
async def move_card(
    card_id: int,
    body: CardMoveRequest,
    session: AsyncSession = Depends(get_session),
) -> DashboardCardOut:
    """Swap this card with its neighbour in the given direction."""
    all_cards = list(
        (
            await session.execute(
                select(DashboardCard).order_by(
                    DashboardCard.position.asc(), DashboardCard.id.asc(),
                )
            )
        ).scalars().all()
    )
    idx = next((i for i, c in enumerate(all_cards) if c.id == card_id), -1)
    if idx == -1:
        raise HTTPException(
            404,
            detail={"error": "not_found", "message": f"card {card_id} not found"},
        )

    target_idx = idx - 1 if body.direction == "up" else idx + 1
    if 0 <= target_idx < len(all_cards):
        a = all_cards[idx]
        b = all_cards[target_idx]
        a.position, b.position = b.position, a.position
        await session.commit()
        return await _resolve_card(session, a)
    # Already at the edge — no-op, just return the card as-is.
    return await _resolve_card(session, all_cards[idx])
