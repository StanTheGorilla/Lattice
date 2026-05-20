"""Alert rules CRUD API."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.models.alert import AlertEvent, AlertRule

router = APIRouter(
    prefix="/alerts", tags=["alerts"], dependencies=[Depends(require_auth)]
)

_VALID_OPS = {"lt", "lte", "gt", "gte"}


class AlertRuleIn(BaseModel):
    metric_name: str
    operator: str
    threshold: float
    label: str
    cooldown_hours: int = 4
    active: bool = True


class AlertRuleOut(BaseModel):
    id: int
    metric_name: str
    operator: str
    threshold: float
    label: str
    cooldown_hours: int
    active: bool
    created_at: str

    model_config = {"from_attributes": True}


class AlertEventOut(BaseModel):
    id: int
    rule_id: int
    fired_at: str
    value: float

    model_config = {"from_attributes": True}


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(session: AsyncSession = Depends(get_session)) -> list[AlertRule]:
    result = await session.execute(select(AlertRule).order_by(AlertRule.id))
    return list(result.scalars().all())


@router.post("/rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: AlertRuleIn, session: AsyncSession = Depends(get_session)
) -> AlertRule:
    if body.operator not in _VALID_OPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_operator", "message": f"operator must be one of {sorted(_VALID_OPS)}"},
        )
    now_iso = datetime.now(ZoneInfo(settings.timezone)).isoformat()
    rule = AlertRule(
        metric_name=body.metric_name,
        operator=body.operator,
        threshold=body.threshold,
        label=body.label,
        cooldown_hours=body.cooldown_hours,
        active=body.active,
        created_at=now_iso,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def patch_rule(
    rule_id: int,
    body: dict[str, object],
    session: AsyncSession = Depends(get_session),
) -> AlertRule:
    rule = await session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert rule not found")
    allowed = {"metric_name", "operator", "threshold", "label", "cooldown_hours", "active"}
    for k, v in body.items():
        if k in allowed:
            setattr(rule, k, v)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    rule = await session.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="alert rule not found")
    await session.delete(rule)
    await session.commit()


@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[AlertEvent]:
    result = await session.execute(
        select(AlertEvent).order_by(AlertEvent.fired_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
