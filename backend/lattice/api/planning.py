"""Planning system endpoints — profile, areas, initiatives, decisions, AI rules.

SPEC §5.x. The planning system is the user-facing layer above raw metrics; it
holds identity, life areas, current bets ("initiatives"), open + closed
decisions, and explicit AI rules.

Conventions:
- Profile is a singleton (`id == 1`). Created lazily; GET always succeeds.
- Areas seed with defaults via the 0006 migration; CRUD is fully exposed.
- Initiatives + decisions: status transitions are explicit (PATCH `status`);
  the API stamps `closed_at` / `decided_at` / `reviewed_at` automatically when
  the relevant status fires.
- All datetimes are ISO 8601 with TZ (UTC for server-generated stamps).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.db import get_session
from lattice.models import AIRule, Area, Decision, Initiative, Plan, Profile
from lattice.schemas.planning import (
    AIRuleCreate,
    AIRuleOut,
    AIRulePatch,
    AreaCreate,
    AreaOut,
    AreaPatch,
    DecisionCreate,
    DecisionOut,
    DecisionPatch,
    InitiativeCreate,
    InitiativeOut,
    InitiativePatch,
    PlanCreate,
    PlanOut,
    PlanPatch,
    ProfileOut,
    ProfilePatch,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["planning"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _today_iso() -> str:
    return date.today().isoformat()


def _age_from_birthday(b: str | None) -> int | None:
    if not b:
        return None
    try:
        bd = date.fromisoformat(b)
    except ValueError:
        return None
    today = date.today()
    return today.year - bd.year - (
        (today.month, today.day) < (bd.month, bd.day)
    )


def _profile_to_out(p: Profile) -> ProfileOut:
    out = ProfileOut.model_validate(p)
    out.age = _age_from_birthday(p.birthday)
    return out


def _decision_to_out(d: Decision) -> DecisionOut:
    options: list[str] | None = None
    if d.options:
        try:
            options = json.loads(d.options)
            if not isinstance(options, list):
                options = None
        except json.JSONDecodeError:
            options = None
    return DecisionOut(
        id=d.id,
        question=d.question,
        area_id=d.area_id,
        initiative_id=d.initiative_id,
        options=options,
        criteria=d.criteria,
        deadline=d.deadline,
        decided_at=d.decided_at,
        decision=d.decision,
        reasoning=d.reasoning,
        confidence=d.confidence,
        review_at=d.review_at,
        reviewed_at=d.reviewed_at,
        outcome=d.outcome,
        outcome_rating=d.outcome_rating,
        status=d.status,
        created_at=d.created_at,
    )


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


async def _get_or_create_profile(session: AsyncSession) -> Profile:
    row = await session.get(Profile, 1)
    if row is None:
        row = Profile(id=1, updated_at=_now_iso())
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


@router.get("/profile", response_model=ProfileOut)
async def get_profile(
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    row = await _get_or_create_profile(session)
    return _profile_to_out(row)


@router.get("/profile/nutrition-goals")
async def get_nutrition_goals(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from lattice.functions.nutrition_goals import merge_with_profile, suggest_goals
    row = await _get_or_create_profile(session)
    suggested = suggest_goals(row.weight_kg, row.height_cm, row.birthday, row.sex_at_birth)
    goals = merge_with_profile(
        {
            "calorie_goal": row.calorie_goal,
            "protein_g_goal": row.protein_g_goal,
            "carbs_g_goal": row.carbs_g_goal,
            "fat_g_goal": row.fat_g_goal,
            "fiber_g_goal": row.fiber_g_goal,
            "sugar_g_goal": row.sugar_g_goal,
        },
        suggested,
    )
    return dict(goals)


@router.patch("/profile", response_model=ProfileOut)
async def patch_profile(
    payload: ProfilePatch,
    session: AsyncSession = Depends(get_session),
) -> ProfileOut:
    row = await _get_or_create_profile(session)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = _now_iso()
    await session.commit()
    await session.refresh(row)
    return _profile_to_out(row)


# --------------------------------------------------------------------------- #
# Areas
# --------------------------------------------------------------------------- #


async def _get_area(session: AsyncSession, area_id: int) -> Area:
    row = await session.get(Area, area_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"area {area_id} not found"},
        )
    return row


@router.get("/areas", response_model=list[AreaOut])
async def list_areas(
    include_archived: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[AreaOut]:
    stmt = select(Area)
    if not include_archived:
        stmt = stmt.where(Area.archived.is_(False))
    stmt = stmt.order_by(Area.sort_order.asc(), Area.name.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return [AreaOut.model_validate(r) for r in rows]


@router.post("/areas", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
async def create_area(
    payload: AreaCreate,
    session: AsyncSession = Depends(get_session),
) -> AreaOut:
    row = Area(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        color=payload.color,
        sort_order=payload.sort_order,
        archived=False,
        created_at=_now_iso(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_key",
                "message": f"area with key {payload.key!r} already exists",
            },
        ) from exc
    await session.refresh(row)
    return AreaOut.model_validate(row)


@router.patch("/areas/{area_id}", response_model=AreaOut)
async def patch_area(
    area_id: int,
    payload: AreaPatch,
    session: AsyncSession = Depends(get_session),
) -> AreaOut:
    row = await _get_area(session, area_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return AreaOut.model_validate(row)


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_area(
    area_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Hard delete — cascades to initiatives, sets decision.area_id to NULL."""
    row = await _get_area(session, area_id)
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# Initiatives
# --------------------------------------------------------------------------- #


async def _get_initiative(session: AsyncSession, init_id: int) -> Initiative:
    row = await session.get(Initiative, init_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"initiative {init_id} not found"},
        )
    return row


@router.get("/initiatives", response_model=list[InitiativeOut])
async def list_initiatives(
    area_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> list[InitiativeOut]:
    stmt = select(Initiative)
    if area_id is not None:
        stmt = stmt.where(Initiative.area_id == area_id)
    if status_filter is not None:
        stmt = stmt.where(Initiative.status == status_filter)
    stmt = stmt.order_by(Initiative.status.asc(), Initiative.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [InitiativeOut.model_validate(r) for r in rows]


@router.post(
    "/initiatives", response_model=InitiativeOut, status_code=status.HTTP_201_CREATED,
)
async def create_initiative(
    payload: InitiativeCreate,
    session: AsyncSession = Depends(get_session),
) -> InitiativeOut:
    await _get_area(session, payload.area_id)
    row = Initiative(
        area_id=payload.area_id,
        title=payload.title,
        why=payload.why,
        target_outcome=payload.target_outcome,
        target_metric=payload.target_metric,
        target_value=payload.target_value,
        target_date=payload.target_date,
        status="active",
        review_at=payload.review_at,
        created_at=_now_iso(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return InitiativeOut.model_validate(row)


_CLOSED_STATUSES = {"completed", "abandoned"}


@router.patch("/initiatives/{init_id}", response_model=InitiativeOut)
async def patch_initiative(
    init_id: int,
    payload: InitiativePatch,
    session: AsyncSession = Depends(get_session),
) -> InitiativeOut:
    row = await _get_initiative(session, init_id)
    data = payload.model_dump(exclude_unset=True)
    if "area_id" in data and data["area_id"] is not None:
        await _get_area(session, data["area_id"])

    new_status = data.get("status")
    if new_status is not None and new_status != row.status:
        if new_status in _CLOSED_STATUSES and row.closed_at is None:
            row.closed_at = _now_iso()
        elif new_status == "active":
            row.closed_at = None

    for k, v in data.items():
        setattr(row, k, v)

    await session.commit()
    await session.refresh(row)
    return InitiativeOut.model_validate(row)


@router.delete("/initiatives/{init_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    init_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_initiative(session, init_id)
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #


async def _get_decision(session: AsyncSession, decision_id: int) -> Decision:
    row = await session.get(Decision, decision_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"decision {decision_id} not found"},
        )
    return row


@router.get("/decisions", response_model=list[DecisionOut])
async def list_decisions(
    status_filter: str | None = Query(default=None, alias="status"),
    area_id: int | None = Query(default=None),
    initiative_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[DecisionOut]:
    stmt = select(Decision)
    if status_filter is not None:
        stmt = stmt.where(Decision.status == status_filter)
    if area_id is not None:
        stmt = stmt.where(Decision.area_id == area_id)
    if initiative_id is not None:
        stmt = stmt.where(Decision.initiative_id == initiative_id)
    stmt = stmt.order_by(Decision.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [_decision_to_out(r) for r in rows]


@router.post(
    "/decisions", response_model=DecisionOut, status_code=status.HTTP_201_CREATED,
)
async def create_decision(
    payload: DecisionCreate,
    session: AsyncSession = Depends(get_session),
) -> DecisionOut:
    if payload.area_id is not None:
        await _get_area(session, payload.area_id)
    if payload.initiative_id is not None:
        await _get_initiative(session, payload.initiative_id)

    row = Decision(
        question=payload.question,
        area_id=payload.area_id,
        initiative_id=payload.initiative_id,
        options=json.dumps(payload.options) if payload.options is not None else None,
        criteria=payload.criteria,
        deadline=payload.deadline,
        status="open",
        created_at=_now_iso(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _decision_to_out(row)


@router.patch("/decisions/{decision_id}", response_model=DecisionOut)
async def patch_decision(
    decision_id: int,
    payload: DecisionPatch,
    session: AsyncSession = Depends(get_session),
) -> DecisionOut:
    row = await _get_decision(session, decision_id)
    data: dict[str, Any] = payload.model_dump(exclude_unset=True)

    if "area_id" in data and data["area_id"] is not None:
        await _get_area(session, data["area_id"])
    if "initiative_id" in data and data["initiative_id"] is not None:
        await _get_initiative(session, data["initiative_id"])

    if "options" in data:
        opts = data.pop("options")
        row.options = json.dumps(opts) if opts is not None else None

    new_status = data.get("status")
    if new_status is not None and new_status != row.status:
        if new_status == "decided" and row.decided_at is None:
            row.decided_at = _now_iso()
        elif new_status == "reviewed" and row.reviewed_at is None:
            row.reviewed_at = _now_iso()

    for k, v in data.items():
        setattr(row, k, v)

    await session.commit()
    await session.refresh(row)
    return _decision_to_out(row)


@router.delete("/decisions/{decision_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_decision(
    decision_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_decision(session, decision_id)
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #


async def _get_plan(session: AsyncSession, plan_id: int) -> Plan:
    row = await session.get(Plan, plan_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"plan {plan_id} not found"},
        )
    return row


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(
    status_filter: str | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_session),
) -> list[PlanOut]:
    stmt = select(Plan)
    if status_filter is not None:
        stmt = stmt.where(Plan.status == status_filter)
    else:
        stmt = stmt.where(Plan.status == "active")
    stmt = stmt.order_by(Plan.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [PlanOut.model_validate(r) for r in rows]


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PlanCreate,
    session: AsyncSession = Depends(get_session),
) -> PlanOut:
    row = Plan(
        goal=payload.goal,
        plan=payload.plan,
        metric=payload.metric,
        target_value=payload.target_value,
        target_date=payload.target_date,
        status="active",
        created_at=_now_iso(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return PlanOut.model_validate(row)


@router.patch("/plans/{plan_id}", response_model=PlanOut)
async def patch_plan(
    plan_id: int,
    payload: PlanPatch,
    session: AsyncSession = Depends(get_session),
) -> PlanOut:
    row = await _get_plan(session, plan_id)
    data = payload.model_dump(exclude_unset=True)
    new_status = data.get("status")
    if new_status is not None and new_status != row.status:
        if new_status in ("completed", "abandoned") and row.closed_at is None:
            row.closed_at = _now_iso()
        elif new_status == "active":
            row.closed_at = None
    for k, v in data.items():
        setattr(row, k, v)
    await session.commit()
    await session.refresh(row)
    return PlanOut.model_validate(row)


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_plan(session, plan_id)
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# AI rules
# --------------------------------------------------------------------------- #


async def _get_rule(session: AsyncSession, rule_id: int) -> AIRule:
    row = await session.get(AIRule, rule_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": f"rule {rule_id} not found"},
        )
    return row


@router.get("/ai-rules", response_model=list[AIRuleOut])
async def list_rules(
    active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[AIRuleOut]:
    stmt = select(AIRule)
    if active is not None:
        stmt = stmt.where(AIRule.active.is_(active))
    stmt = stmt.order_by(AIRule.created_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [AIRuleOut.model_validate(r) for r in rows]


@router.post(
    "/ai-rules", response_model=AIRuleOut, status_code=status.HTTP_201_CREATED,
)
async def create_rule(
    payload: AIRuleCreate,
    session: AsyncSession = Depends(get_session),
) -> AIRuleOut:
    row = AIRule(
        rule=payload.rule,
        scope=payload.scope,
        scope_id=payload.scope_id,
        active=payload.active,
        created_at=_now_iso(),
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_rule",
                "message": "an identical rule already exists",
            },
        ) from exc
    await session.refresh(row)
    return AIRuleOut.model_validate(row)


@router.patch("/ai-rules/{rule_id}", response_model=AIRuleOut)
async def patch_rule(
    rule_id: int,
    payload: AIRulePatch,
    session: AsyncSession = Depends(get_session),
) -> AIRuleOut:
    row = await _get_rule(session, rule_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "duplicate_rule", "message": "rule text collides"},
        ) from exc
    await session.refresh(row)
    return AIRuleOut.model_validate(row)


@router.delete("/ai-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_rule(session, rule_id)
    await session.delete(row)
    await session.commit()
