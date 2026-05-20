"""Metrics endpoints (SPEC §5.3)."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import Metric
from lattice.schemas.metrics import (
    BaselineResponse,
    MetricListResponse,
    MetricOut,
    MetricsLatestResponse,
)

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_auth)])


@router.get("", response_model=MetricListResponse, response_model_by_alias=True)
async def list_metrics(
    name: str | None = Query(default=None, description="Filter by metric_name (exact)"),
    from_: str | None = Query(default=None, alias="from", description="ISO timestamp (inclusive)"),
    to: str | None = Query(default=None, description="ISO timestamp (inclusive)"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> MetricListResponse:
    where = []
    if name is not None:
        where.append(Metric.metric_name == name)
    if from_ is not None:
        where.append(Metric.timestamp >= from_)
    if to is not None:
        where.append(Metric.timestamp <= to)

    total_stmt = select(func.count(Metric.id))
    if where:
        total_stmt = total_stmt.where(*where)
    total = (await session.execute(total_stmt)).scalar_one()

    stmt = select(Metric)
    if where:
        stmt = stmt.where(*where)
    stmt = stmt.order_by(Metric.timestamp.desc()).limit(limit).offset(offset)
    rows = (await session.execute(stmt)).scalars().all()

    return MetricListResponse(
        items=[MetricOut.model_validate(r) for r in rows],
        total=int(total),
    )


@router.get("/latest", response_model=MetricsLatestResponse, response_model_by_alias=True)
async def latest(
    names: str = Query(..., description="Comma-separated metric names"),
    session: AsyncSession = Depends(get_session),
) -> MetricsLatestResponse:
    name_list = [n.strip() for n in names.split(",") if n.strip()]
    out: dict[str, MetricOut | None] = {}
    for n in name_list:
        stmt = (
            select(Metric)
            .where(Metric.metric_name == n)
            .order_by(Metric.timestamp.desc())
            .limit(1)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        out[n] = MetricOut.model_validate(row) if row is not None else None
    return MetricsLatestResponse(items=out)


@router.get("/baseline", response_model=BaselineResponse)
async def baseline(
    name: str = Query(..., description="Metric name"),
    days: int = Query(default=14, ge=2, le=90),
    session: AsyncSession = Depends(get_session),
) -> BaselineResponse:
    """Rolling mean/SD over the most recent `days` rows for `name`."""
    stmt = (
        select(Metric.value)
        .where(Metric.metric_name == name)
        .order_by(Metric.timestamp.desc())
        .limit(days)
    )
    values = [float(v) for v in (await session.execute(stmt)).scalars().all()]
    n = len(values)
    if n == 0:
        return BaselineResponse(name=name, mean=None, sd=None, n=0, window_days=days)
    mean = sum(values) / n
    if n < 2:
        return BaselineResponse(name=name, mean=mean, sd=None, n=n, window_days=days)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return BaselineResponse(
        name=name, mean=mean, sd=math.sqrt(variance), n=n, window_days=days,
    )
