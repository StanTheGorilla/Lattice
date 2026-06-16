"""Chat agent loop + in-process tool dispatcher (SPEC §7).

The chat endpoint runs:
1. Build messages = [system, ...history, user_message]
2. Loop:
   a. Call DeepSeek with TOOL_SCHEMAS
   b. If choice.message.tool_calls: execute each via execute_tool,
      append {role: 'tool', tool_call_id, content: <json>} for each
   c. Else: return choice.message.content as final reply
3. Cap iterations at settings.chat_max_iterations to avoid runaway loops.

Tools dispatch in-process to the existing `functions/`, `sync/`, and API logic
— no HTTP round-trip. The router does the same parameter coercion the API
layer does (date parsing, payload validation), so the LLM gets the same error
messages a human would see hitting the endpoint directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.advisor import compute_advisor
from lattice.functions.allostatic_load import compute_allostatic_load
from lattice.functions.changepoint import detect_changepoints
from lattice.functions.data_freshness import get_data_freshness
from lattice.functions.initiative_metrics import get_initiative_metrics
from lattice.functions.lagged_correlate import compute_lagged_correlation
from lattice.functions.recovery_trajectory import compute_recovery_trajectory
from lattice.functions.sleep_architecture import compute_sleep_architecture
from lattice.functions.sleep_debt import compute_sleep_debt
from lattice.functions.sleep_regularity import compute_sleep_regularity
from lattice.functions.training_response import compute_training_load_response
from lattice.functions.trends import trend_direction
from lattice.functions.caffeine import compute_caffeine_status
from lattice.functions.calendar_load import busy_hours_per_day
from lattice.functions.habits_adherence import compute_habit_adherence
from lattice.functions.quick_context import get_quick_context
from lattice.functions.readiness import compute_readiness
from lattice.functions.recommendation_store import (
    get_active_sleep_recommendation,
    set_sleep_recommendation,
    tonight_target_date,
)
from lattice.functions.recovery import recovery_after
from lattice.functions.sleep_pattern import (
    sleep_pattern,
    sleep_stages_for_night,
    sleep_stages_pattern,
)
from lattice.functions.stats import (
    body_battery_drop_rate,
    body_battery_hourly_deltas,
    compare_windows,
    correlate,
    daily_series,
    stats_by_hour,
    stats_by_weekday,
    stats_for_metric,
    stress_burden_by_zone,
    time_of_day_distribution,
)
from lattice.functions.training_rec import compute_training_rec
from lattice.functions.work_windows import compute_work_windows
from lattice.functions.workout_queries import (
    last_workout,
    list_workouts,
    workout_stats,
)
from lattice.integrations.deepseek import chat_completion
from lattice.llm.budget import check_budget, record_usage
from lattice.llm.f9b_validator import enforce as f9b_enforce
from lattice.llm.model_selector import pick_chat_model
from lattice.llm.prompts import build_planning_context, build_system_prompt
from lattice.llm.sandbox import execute_algorithm, fetch_algorithm_data, validate_code
from lattice.llm.tools import TOOL_SCHEMAS
from lattice.models import (
    CalendarCache,
    CustomAlgorithm,
    DashboardCard,
    Entry,
    HabitCheckin,
    HabitDefinition,
    Metric,
)
from lattice.schemas.dashboard import DataSourceLineBar, DataSourceTable
from lattice.schemas.entries import validate_data_for_type
from lattice.sync.calendar_sync import (
    cached_events_or_refresh,
    create_event_remote,
    delete_event_remote,
    patch_event_remote,
    row_to_event_body,
    sync_window,
)
from lattice.sync.garmin_sync import sync_recent
from lattice.utils import normalize_to_local_iso

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    ok: bool


@dataclass(slots=True)
class AgentResult:
    reply: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    finish_reason: str = "stop"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _today_local(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def _parse_date(value: str | None, tz: str) -> date:
    if value is None:
        return _today_local(tz)
    return date.fromisoformat(value)


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    """Build a standard error payload sent back to the LLM as a tool result."""
    return {"error": msg, **extra}


def _dump(obj: Any) -> Any:
    """Convert a pydantic model (or list/dict thereof) to plain JSON-safe data."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(by_alias=True, mode="json")
    if isinstance(obj, list):
        return [_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------- #
# Per-tool handlers (signature: async (session, args) -> dict)
# --------------------------------------------------------------------------- #


async def _h_get_today_overview(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    today = _today_local(tz)
    freshness = await get_data_freshness(session)
    readiness = await compute_readiness(session, target=today, tz=tz)
    training = await compute_training_rec(
        session, target=today, tz=tz, readiness_score=readiness.score,
    )
    sleep = await get_active_sleep_recommendation(session, target=today, tz=tz)
    caffeine = await compute_caffeine_status(session, at=datetime.now(ZoneInfo(tz)), tz=tz)
    windows = await compute_work_windows(
        session, target=today, tz=tz, min_minutes=60, readiness_score=readiness.score,
    )
    return {
        "date": today.isoformat(),
        "data_freshness": freshness,
        "readiness": _dump(readiness),
        "training_recommendation": _dump(training),
        "sleep_window": _dump(sleep),
        "caffeine_status": _dump(caffeine),
        "top_work_window": _dump(windows.windows[0]) if windows.windows else None,
        "peak_focus_hour": windows.peak_focus_hour,
    }


async def _h_check_data_freshness(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await get_data_freshness(session)


async def _h_get_readiness(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    return _dump(await compute_readiness(session, target=target, tz=tz))


async def _h_get_advice(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    intent = args.get("intent")
    if intent not in ("learn", "train", "rest", "creative", "meeting", "physical_task"):
        return _err(f"invalid intent: {intent!r}")
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    return _dump(await compute_advisor(session, intent=intent, target=target, tz=tz))


async def _h_get_work_windows(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    min_minutes = int(args.get("min_minutes") or 60)
    readiness = await compute_readiness(session, target=target, tz=tz)
    return _dump(
        await compute_work_windows(
            session, target=target, tz=tz, min_minutes=min_minutes,
            readiness_score=readiness.score,
        ),
    )


async def _h_get_training_recommendation(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    readiness = await compute_readiness(session, target=target, tz=tz)
    return _dump(
        await compute_training_rec(
            session, target=target, tz=tz, readiness_score=readiness.score,
        ),
    )


async def _h_get_sleep_window(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    return _dump(await get_active_sleep_recommendation(session, target=target, tz=tz))


async def _h_set_sleep_recommendation(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    tz = settings.timezone
    raw_date = args.get("date")
    target = _parse_date(raw_date, tz) if raw_date else tonight_target_date(tz)
    bedtime = args.get("bedtime")
    wake_time = args.get("wake_time")
    if not isinstance(bedtime, str) or not bedtime.strip():
        return _err("bedtime required (HH:MM local, or ISO 8601)")
    if not isinstance(wake_time, str) or not wake_time.strip():
        return _err("wake_time required (HH:MM local, or ISO 8601)")
    dur_raw = args.get("target_duration_min")
    try:
        duration = float(dur_raw) if dur_raw is not None else None
    except (TypeError, ValueError):
        return _err("target_duration_min must be a number (minutes)")
    rationale = args.get("rationale")
    try:
        rec = await set_sleep_recommendation(
            session,
            target=target,
            tz=tz,
            bedtime=bedtime.strip(),
            wake_time=wake_time.strip(),
            target_duration_min=duration,
            rationale=rationale.strip() if isinstance(rationale, str) else None,
            author="chat",
        )
    except (ValueError, KeyError) as exc:
        return _err(f"could not parse times: {exc}")
    return _dump(rec)


async def _h_get_health_targets(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    """Return every active health target with provenance + outer bounds.

    Lets the AI inspect what it (or the seed) currently has on file before
    deciding whether to call `set_health_targets`.
    """
    from lattice.functions.health_targets import (
        ALL_KINDS,
        get_all_targets,
        outer_bounds,
    )
    from lattice.functions.sleep_window import _age_on
    from lattice.models import Profile as _Profile

    profile = await session.get(_Profile, 1)
    age = _age_on(profile.birthday, datetime.now(ZoneInfo(settings.timezone)).date()) if profile else None
    targets = await get_all_targets(session)
    out: list[dict[str, Any]] = []
    for kind in ALL_KINDS:
        t = targets[kind]
        lo, hi = outer_bounds(kind, age)
        out.append({
            "kind": kind,
            "value": t.value,
            "source": t.source,
            "rationale": t.rationale,
            "author": t.author,
            "bounds_for_age": {"min": lo, "max": hi},
        })
    return {"age": age, "targets": out}


async def _h_set_health_targets(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    """Persist one or more AI-set health targets (V — versatility rework).

    Values outside the per-age outer guardrails are clamped on write; the
    clamp note is appended to the rationale so every surface displaying the
    target shows "requested X, clamped to Y" automatically.
    """
    from lattice.functions.health_targets import (
        ALL_KINDS,
        HealthTargetWrite,
        set_health_targets,
    )

    raw = args.get("targets")
    if not isinstance(raw, list) or not raw:
        return _err("`targets` must be a non-empty list of {kind, value} objects")
    writes: list[HealthTargetWrite] = []
    for item in raw:
        if not isinstance(item, dict):
            return _err("each target must be an object with `kind` and `value`")
        kind = item.get("kind")
        if kind not in ALL_KINDS:
            return _err(
                f"unknown kind '{kind}'; allowed: {', '.join(ALL_KINDS)}",
            )
        try:
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            return _err(f"`value` for {kind} must be a number")
        writes.append(HealthTargetWrite(kind=kind, value=value))
    rationale = args.get("rationale")
    rationale_str = (
        rationale.strip() if isinstance(rationale, str) and rationale.strip() else None
    )
    results = await set_health_targets(
        session, writes=writes, rationale=rationale_str, author="chat",
    )
    return {
        "written": [
            {
                "kind": r.kind,
                "requested": r.requested,
                "stored": r.stored,
                "clamped": r.clamped,
                "bounds": {"min": r.bounds[0], "max": r.bounds[1]},
                "rationale": r.rationale,
            }
            for r in results
        ],
    }


async def _h_get_caffeine_status(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    zone = ZoneInfo(tz)
    at_raw = args.get("at")
    if at_raw:
        at_dt = datetime.fromisoformat(at_raw)
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=zone)
    else:
        at_dt = datetime.now(zone)
    return _dump(await compute_caffeine_status(session, at=at_dt, tz=tz))


async def _h_get_metric(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return _err("name is required")
    limit = max(1, min(int(args.get("limit") or 1), 365))
    stmt = (
        select(Metric)
        .where(Metric.metric_name == name)
        .order_by(Metric.timestamp.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        return {"name": name, "count": 0, "items": []}
    return {
        "name": name,
        "count": len(rows),
        "items": [
            {
                "timestamp": r.timestamp,
                "value": r.value,
                "unit": r.unit,
                "source": r.source,
            }
            for r in rows
        ],
    }


async def _h_get_baseline(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not name:
        return _err("name is required")
    days = max(2, min(int(args.get("days") or 14), 365))
    stmt = (
        select(Metric.value)
        .where(Metric.metric_name == name)
        .order_by(Metric.timestamp.desc())
        .limit(days)
    )
    values = [float(v) for v in (await session.execute(stmt)).scalars().all()]
    n = len(values)
    if n == 0:
        return {"name": name, "mean": None, "sd": None, "n": 0, "window_days": days}
    mean = sum(values) / n
    if n < 2:
        return {"name": name, "mean": mean, "sd": None, "n": n, "window_days": days}
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return {"name": name, "mean": mean, "sd": math.sqrt(variance), "n": n, "window_days": days}


async def _h_get_calendar(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    time_min = args.get("from")
    time_max = args.get("to")
    if not time_min or not time_max:
        return _err("'from' and 'to' are required (ISO 8601)")
    # Google Calendar API requires RFC3339 datetimes with TZ. The LLM often
    # passes date-only strings (YYYY-MM-DD); coerce those to midnight/EOD local.
    zone = ZoneInfo(settings.timezone)
    if len(time_min) == 10:
        try:
            d = date.fromisoformat(time_min)
            time_min = datetime.combine(d, datetime.min.time(), tzinfo=zone).isoformat()
        except ValueError:
            pass
    if len(time_max) == 10:
        try:
            d = date.fromisoformat(time_max)
            time_max = datetime.combine(d, datetime.max.time().replace(microsecond=0), tzinfo=zone).isoformat()
        except ValueError:
            pass
    rows = await cached_events_or_refresh(session, time_min, time_max)
    return {
        "from": time_min,
        "to": time_max,
        "count": len(rows),
        "items": [
            {
                "id": r.google_event_id,
                "title": r.title,
                "start": r.start,
                "end": r.end,
                "is_all_day": bool(r.is_all_day),
                "description": r.description,
                "location": r.location,
            }
            for r in rows
        ],
    }


async def _h_get_entries(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    where: list[Any] = []
    type_ = args.get("type")
    if type_:
        where.append(Entry.type == type_)
    if args.get("from"):
        where.append(Entry.timestamp >= args["from"])
    if args.get("to"):
        where.append(Entry.timestamp <= args["to"])
    limit = max(1, min(int(args.get("limit") or 50), 200))
    stmt = select(Entry)
    if where:
        stmt = stmt.where(*where)
    stmt = stmt.order_by(Entry.timestamp.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for r in rows:
        try:
            data = json.loads(r.data)
        except json.JSONDecodeError:
            data = {"_raw": r.data}
        items.append({
            "id": r.id,
            "type": r.type,
            "timestamp": r.timestamp,
            "data": data,
            "source": r.source,
        })
    return {"count": len(items), "items": items}


async def _h_list_habits(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    stmt = select(HabitDefinition)
    if args.get("active_only"):
        stmt = stmt.where(HabitDefinition.active.is_(True))
    stmt = stmt.order_by(HabitDefinition.name.asc())
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "target_per_week": r.target_per_week,
                "active": bool(r.active),
            }
            for r in rows
        ],
    }


async def _h_get_habit_adherence(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    today = _today_local(tz)
    from_d = _parse_date(args.get("from"), tz) if args.get("from") else today.replace(day=1)
    to_d = _parse_date(args.get("to"), tz) if args.get("to") else today
    if from_d > to_d:
        return _err("from > to")
    return _dump(
        await compute_habit_adherence(session, from_=from_d, to=to_d, today=today),
    )


# --------------------------------------------------------------------------- #
# Write handlers
# --------------------------------------------------------------------------- #


async def _h_log_entry(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    type_ = args.get("type")
    data = args.get("data")
    if not isinstance(type_, str) or not isinstance(data, dict):
        return _err("type (str) and data (object) required")
    try:
        validated = validate_data_for_type(type_, data)
    except (ValidationError, ValueError) as exc:
        return _err("data failed schema validation", details=str(exc))
    now = _now_iso()
    # P1-1: event timestamps are stored in the local-TZ offset family so they
    # sort correctly against the local cutoffs every functions/ query builds.
    raw_ts = args.get("timestamp")
    timestamp = (
        normalize_to_local_iso(raw_ts)
        if isinstance(raw_ts, str) and raw_ts
        else datetime.now(ZoneInfo(settings.timezone)).isoformat(timespec="seconds")
    )
    stored_data = validated.model_dump(exclude={"type"})

    # Auto-estimate nutrition for food entries (best-effort, never fails the log)
    if type_ == "food":
        description = stored_data.get("description", "")
        grams = stored_data.get("grams")
        if description:
            try:
                from lattice.functions.nutrition import estimate_nutrition
                est = await asyncio.wait_for(
                    estimate_nutrition(description, grams),
                    timeout=12.0,
                )
                if est is not None:
                    stored_data["nutrition"] = est.to_dict()
            except Exception:
                pass

    row = Entry(
        timestamp=timestamp,
        logged_at=now,
        type=type_,
        data=json.dumps(stored_data),
        source="discord",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        "id": row.id,
        "type": row.type,
        "timestamp": row.timestamp,
        "data": json.loads(row.data),
    }


async def _h_delete_entry(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    entry_id = args.get("entry_id")
    if not isinstance(entry_id, int):
        return _err("entry_id (int) required")
    row = await session.get(Entry, entry_id)
    if row is None:
        return _err(f"entry {entry_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": entry_id}


async def _h_patch_entry(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    entry_id = args.get("entry_id")
    if not isinstance(entry_id, int):
        return _err("entry_id (int) required")
    row = await session.get(Entry, entry_id)
    if row is None:
        return _err(f"entry {entry_id} not found")
    if args.get("timestamp"):
        row.timestamp = args["timestamp"]
    if args.get("data") is not None:
        try:
            validated = validate_data_for_type(row.type, args["data"])
        except (ValidationError, ValueError) as exc:
            return _err("data failed schema validation", details=str(exc))
        row.data = json.dumps(validated.model_dump(exclude={"type"}))
    await session.commit()
    await session.refresh(row)
    return {
        "id": row.id,
        "type": row.type,
        "timestamp": row.timestamp,
        "data": json.loads(row.data),
    }


async def _h_get_nutrition_goals(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    from lattice.functions.nutrition_goals import merge_with_profile, suggest_goals
    from lattice.models import Profile as _Profile
    row = await session.get(_Profile, 1)
    if row is None:
        suggested = suggest_goals(None, None, None, None)
        return dict(suggested)
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


async def _h_set_nutrition_goals(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    from lattice.models import Profile as _Profile
    row = await session.get(_Profile, 1)
    if row is None:
        from datetime import UTC, datetime
        row = _Profile(id=1, updated_at=datetime.now(UTC).isoformat(timespec="seconds"))
        session.add(row)
    _GOAL_FIELDS = ("calorie_goal", "protein_g_goal", "carbs_g_goal", "fat_g_goal", "fiber_g_goal", "sugar_g_goal")
    for field in _GOAL_FIELDS:
        if field in args and args[field] is not None:
            setattr(row, field, float(args[field]))
    await session.commit()
    await session.refresh(row)
    return {f: getattr(row, f) for f in _GOAL_FIELDS}


async def _resolve_habit(
    session: AsyncSession, args: dict[str, Any],
) -> tuple[HabitDefinition | None, dict[str, Any] | None]:
    habit_id = args.get("habit_id")
    name = args.get("name")
    if habit_id is not None:
        row = await session.get(HabitDefinition, int(habit_id))
        if row is None:
            return None, _err(f"habit_id {habit_id} not found")
        return row, None
    if name:
        stmt = select(HabitDefinition).where(func.lower(HabitDefinition.name) == name.lower())
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None, _err(f"habit named {name!r} not found")
        return row, None
    return None, _err("habit_id or name required")


async def _h_check_habit(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    row, error = await _resolve_habit(session, args)
    if error is not None or row is None:
        return error or _err("habit lookup failed")
    tz = settings.timezone
    target = _parse_date(args.get("date"), tz)
    completed = bool(args.get("completed", True))
    stmt = sqlite_insert(HabitCheckin.__table__).values(
        habit_id=row.id,
        date=target.isoformat(),
        completed=completed,
        note=None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["habit_id", "date"],
        set_={"completed": stmt.excluded.completed},
    )
    await session.execute(stmt)
    await session.commit()
    return {
        "habit_id": row.id,
        "habit_name": row.name,
        "date": target.isoformat(),
        "completed": completed,
    }


async def _h_create_calendar_event(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    title = args.get("title")
    start = args.get("start")
    end = args.get("end")
    if not title or not start or not end:
        return _err("title, start, end are required")
    # Cross-turn idempotency: if a cached event already has the same title and
    # exact start/end, treat this as an accidental repeat (the model re-issuing
    # a create it already made in a prior turn) and return the existing event
    # instead of POSTing a duplicate to Google. The within-turn dedup handles
    # parallel repeats in one turn; this covers the across-turn case.
    existing = (
        await session.execute(
            select(CalendarCache).where(
                CalendarCache.title == title,
                CalendarCache.start == start,
                CalendarCache.end == end,
            ),
        )
    ).scalars().first()
    if existing is not None:
        return {
            "id": existing.google_event_id,
            "title": existing.title,
            "start": existing.start,
            "end": existing.end,
            "is_all_day": bool(existing.is_all_day),
            "note": (
                "an identical event already exists at this time — returning it "
                "instead of creating a duplicate"
            ),
        }
    body = row_to_event_body(
        title=title,
        start=start,
        end=end,
        description=args.get("description"),
        location=args.get("location"),
        is_all_day=bool(args.get("is_all_day", False)),
        timezone_name=settings.timezone,
    )
    row = await create_event_remote(session, body)
    return {
        "id": row.google_event_id,
        "title": row.title,
        "start": row.start,
        "end": row.end,
        "is_all_day": bool(row.is_all_day),
    }


async def _h_patch_calendar_event(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    event_id = args.get("event_id")
    if not event_id:
        return _err("event_id required")
    body: dict[str, Any] = {}
    if "title" in args and args["title"] is not None:
        body["summary"] = args["title"]
    if "description" in args and args["description"] is not None:
        body["description"] = args["description"]
    if "location" in args and args["location"] is not None:
        body["location"] = args["location"]
    start = args.get("start")
    end = args.get("end")
    if (start is None) ^ (end is None):
        return _err("start and end must be patched together")
    if start is not None and end is not None:
        all_day = bool(args.get("is_all_day", False))
        if all_day:
            body["start"] = {"date": start}
            body["end"] = {"date": end}
        else:
            body["start"] = {"dateTime": start, "timeZone": settings.timezone}
            body["end"] = {"dateTime": end, "timeZone": settings.timezone}
    if not body:
        return _err("no fields to update")
    row = await patch_event_remote(session, event_id, body)
    return {
        "id": row.google_event_id,
        "title": row.title,
        "start": row.start,
        "end": row.end,
    }


async def _h_delete_calendar_event(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    event_id = args.get("event_id")
    if not event_id:
        return _err("event_id required")
    await delete_event_remote(session, event_id)
    return {"id": event_id, "deleted": True}


async def _h_sync_garmin(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    days = max(1, min(int(args.get("days") or 1), 400))
    report = await sync_recent(session, days=days)
    return {
        "metrics_written": report.rows_written,
        "workouts_written": report.workouts_written,
        "samples_written": report.samples_written,
        "dates": report.dates,
        "errors": report.errors,
    }


async def _h_sync_calendar(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    time_min = now.isoformat(timespec="seconds")
    time_max = (now + timedelta(days=14)).isoformat(timespec="seconds")
    written = await sync_window(session, time_min, time_max)
    return {"refreshed": written, "from": time_min, "to": time_max}


# --------------------------------------------------------------------------- #
# Analytical / stats handlers
# --------------------------------------------------------------------------- #


async def _h_get_quick_context(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    return await get_quick_context(session)


async def _h_stats_for_metric(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or not name:
        return _err("name is required")
    return await stats_for_metric(session, name, args.get("from"), args.get("to"))


async def _h_stats_by_hour(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    h0 = args.get("hour_start")
    h1 = args.get("hour_end")
    if not isinstance(name, str) or not isinstance(h0, int) or not isinstance(h1, int):
        return _err("name, hour_start, hour_end required")
    return await stats_by_hour(session, name, h0, h1, args.get("from"), args.get("to"))


async def _h_stats_by_weekday(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    wd = args.get("weekdays")
    if not isinstance(name, str) or not isinstance(wd, list):
        return _err("name and weekdays (list) required")
    try:
        weekdays = [int(d) for d in wd]
    except (TypeError, ValueError):
        return _err("weekdays must be integers 0..6")
    return await stats_by_weekday(session, name, weekdays, args.get("from"), args.get("to"))


async def _h_daily_series(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str):
        return _err("name required")
    return await daily_series(session, name, args.get("from"), args.get("to"))


async def _h_compare_windows(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str):
        return _err("name required")
    return await compare_windows(
        session,
        name,
        args.get("a_from"), args.get("a_to"),
        args.get("b_from"), args.get("b_to"),
        a_hour_start=args.get("a_hour_start"),
        a_hour_end=args.get("a_hour_end"),
        b_hour_start=args.get("b_hour_start"),
        b_hour_end=args.get("b_hour_end"),
    )


async def _h_correlate(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    a = args.get("metric_a")
    b = args.get("metric_b")
    if not isinstance(a, str) or not isinstance(b, str):
        return _err("metric_a and metric_b required")
    return await correlate(session, a, b, args.get("from"), args.get("to"))


async def _h_time_of_day_distribution(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str):
        return _err("name required")
    return await time_of_day_distribution(session, name, args.get("from"), args.get("to"))


async def _h_stress_burden_by_zone(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await stress_burden_by_zone(
        session,
        args.get("from"), args.get("to"),
        args.get("hour_start"), args.get("hour_end"),
    )


async def _h_list_workouts(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    return await list_workouts(
        session, args.get("from"), args.get("to"), args.get("kind"),
    )


async def _h_workout_stats(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    return await workout_stats(
        session, args.get("from"), args.get("to"), args.get("kind"),
    )


async def _h_last_workout(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    return await last_workout(session, args.get("kind"))


async def _h_sleep_pattern(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    return await sleep_pattern(session, args.get("from"), args.get("to"))


async def _h_sleep_stages_for_night(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    night = args.get("night_date")
    if not isinstance(night, str) or len(night) != 10:
        return _err("night_date (YYYY-MM-DD) required")
    return await sleep_stages_for_night(session, night)


async def _h_sleep_stages_pattern(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await sleep_stages_pattern(session, args.get("from"), args.get("to"))


async def _h_body_battery_drop_rate(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await body_battery_drop_rate(
        session,
        args.get("from"), args.get("to"),
        args.get("hour_start"), args.get("hour_end"),
    )


async def _h_body_battery_hourly_deltas(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await body_battery_hourly_deltas(
        session, args.get("from"), args.get("to"),
    )


async def _h_recovery_after(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    kind = args.get("activity_kind")
    if not isinstance(kind, str) or not kind:
        return _err("activity_kind required")
    lookback = int(args.get("lookback_days") or 90)
    return await recovery_after(session, kind, lookback)


async def _h_busy_hours_per_day(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await busy_hours_per_day(session, args.get("from"), args.get("to"))


async def _h_trend_direction(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("metric_name")
    if not isinstance(name, str) or not name:
        return _err("metric_name required")
    return await trend_direction(session, name, args.get("from"), args.get("to"))


async def _h_sleep_debt(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    tz = settings.timezone
    days = max(2, min(int(args.get("days") or 7), 90))
    return await compute_sleep_debt(session, days=days, tz=tz)


async def _h_get_initiative_metrics(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    return await get_initiative_metrics(session)


async def _h_analyze_food(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.functions.nutrition import estimate_nutrition

    description = args.get("description")
    if not isinstance(description, str) or not description.strip():
        return _err("description required")
    grams = float(args["grams"]) if args.get("grams") is not None else None
    est = await estimate_nutrition(description.strip(), grams)
    if est is None:
        return _err("nutrition estimation unavailable (API key missing or service down)")
    return est.to_dict()


async def _h_get_daily_nutrition(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    import json as _json
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo
    from sqlalchemy import select as _select
    from lattice.models import Entry as _Entry

    tz = ZoneInfo(settings.timezone)
    raw_date = args.get("date")
    if raw_date:
        try:
            target_date = date.fromisoformat(raw_date)
        except ValueError:
            target_date = datetime.now(UTC).astimezone(tz).date()
    else:
        target_date = datetime.now(UTC).astimezone(tz).date()

    day_start = f"{target_date.isoformat()}T00:00:00"
    day_end = f"{target_date.isoformat()}T23:59:59"

    stmt = (
        _select(_Entry)
        .where(
            _Entry.type == "food",
            _Entry.timestamp >= day_start,
            _Entry.timestamp <= day_end,
        )
        .order_by(_Entry.timestamp.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    _KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g")
    totals: dict[str, float] = {k: 0.0 for k in _KEYS}
    meals: list[dict[str, Any]] = []

    for row in rows:
        try:
            data = _json.loads(row.data)
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

    return {
        "date": target_date.isoformat(),
        "meals_logged": len(meals),
        "has_nutrition": any(m["nutrition"] is not None for m in meals),
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "meals": meals,
    }


async def _h_get_nutrition_history(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    import json as _json
    from datetime import UTC, date, datetime, timedelta
    from zoneinfo import ZoneInfo
    from sqlalchemy import select as _select
    from lattice.models import Entry as _Entry, Profile as _Profile
    from lattice.functions.nutrition_goals import merge_with_profile, suggest_goals

    tz = ZoneInfo(settings.timezone)
    days = max(1, min(int(args.get("days") or 14), 90))
    today = datetime.now(UTC).astimezone(tz).date()
    from_date = today - timedelta(days=days - 1)

    stmt = (
        _select(_Entry)
        .where(
            _Entry.type == "food",
            _Entry.timestamp >= f"{from_date.isoformat()}T00:00:00",
            _Entry.timestamp <= f"{today.isoformat()}T23:59:59",
        )
        .order_by(_Entry.timestamp.asc())
    )
    rows = list((await session.execute(stmt)).scalars().all())

    _KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g")
    by_day: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            data = _json.loads(row.data)
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

    profile = await session.get(_Profile, 1)
    if profile:
        suggested = suggest_goals(profile.weight_kg, profile.height_cm, profile.birthday, profile.sex_at_birth)
        goals = merge_with_profile(
            {
                "calorie_goal": profile.calorie_goal,
                "protein_g_goal": profile.protein_g_goal,
                "carbs_g_goal": profile.carbs_g_goal,
                "fat_g_goal": profile.fat_g_goal,
                "fiber_g_goal": profile.fiber_g_goal,
                "sugar_g_goal": profile.sugar_g_goal,
            },
            suggested,
        )
    else:
        from lattice.functions.nutrition_goals import NutritionGoals
        goals = NutritionGoals(calorie_goal=2000.0, protein_g_goal=100.0, carbs_g_goal=250.0,
                               fat_g_goal=65.0, fiber_g_goal=28.0, sugar_g_goal=50.0, source="default")

    def _hit(key: str, val: float) -> bool:
        goal = goals[key + "_goal"] if key != "calories" else goals["calorie_goal"]  # type: ignore[literal-required]
        if key in ("protein_g", "fiber_g"):
            return val >= goal * 0.8
        if key in ("sugar_g",):
            return val <= goal * 1.1
        if key == "calories":
            return 0.8 * goal <= val <= 1.15 * goal
        return val <= goal * 1.15  # carbs, fat

    series = []
    for day_str, totals in sorted(by_day.items()):
        hit_map = {}
        for k in _KEYS:
            goal_key = "calorie_goal" if k == "calories" else f"{k}_goal"
            goal_val = goals[goal_key]  # type: ignore[literal-required]
            hit_map[k] = _hit(k, totals[k])
        series.append({
            "date": day_str,
            "totals": {k: round(totals[k], 1) for k in _KEYS},
            "hit": hit_map,
            "overall_hit": sum(hit_map.values()) >= 4,
        })

    days_logged = len(series)
    days_hit_calories = sum(1 for d in series if d["hit"]["calories"])
    days_hit_protein = sum(1 for d in series if d["hit"]["protein_g"])
    return {
        "goals": dict(goals),
        "series": series,
        "summary": {
            "days_with_data": days_logged,
            "days_hit_calories": days_hit_calories,
            "days_hit_protein": days_hit_protein,
        },
    }


async def _h_sleep_regularity(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    days = max(7, min(int(args.get("days") or 30), 90))
    return await compute_sleep_regularity(session, days=days)


async def _h_lagged_correlation(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    a = args.get("metric_a")
    b = args.get("metric_b")
    if not isinstance(a, str) or not isinstance(b, str):
        return _err("metric_a and metric_b required")
    max_lag = max(1, min(int(args.get("max_lag") or 7), 14))
    days = max(30, min(int(args.get("days") or 90), 365))
    return await compute_lagged_correlation(session, metric_a=a, metric_b=b, max_lag=max_lag, days=days)


async def _h_detect_changepoints(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("metric_name")
    if not isinstance(name, str) or not name:
        return _err("metric_name required")
    days = max(21, min(int(args.get("days") or 90), 365))
    return await detect_changepoints(session, metric_name=name, days=days)


async def _h_recovery_trajectory(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    kind = args.get("activity_kind")
    if not isinstance(kind, str) or not kind:
        return _err("activity_kind required")
    lookback = max(30, min(int(args.get("lookback_days") or 180), 365))
    return await compute_recovery_trajectory(session, activity_kind=kind, lookback_days=lookback)


async def _h_allostatic_load(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    baseline = max(30, min(int(args.get("baseline_days") or 90), 365))
    recent = max(1, min(int(args.get("recent_days") or 7), 14))
    return await compute_allostatic_load(session, baseline_days=baseline, recent_days=recent)


async def _h_sleep_architecture(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    days = max(3, min(int(args.get("days") or 14), 30))
    return await compute_sleep_architecture(session, days=days)


async def _h_training_load_response(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    days = max(14, min(int(args.get("days") or 60), 180))
    return await compute_training_load_response(session, days=days)


async def _h_save_plan(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from datetime import UTC, datetime

    from lattice.models import Plan

    goal = args.get("goal")
    plan_text = args.get("plan")
    if not isinstance(goal, str) or not goal.strip():
        return _err("goal required")
    if not isinstance(plan_text, str) or not plan_text.strip():
        return _err("plan required")
    row = Plan(
        goal=goal.strip(),
        plan=plan_text.strip(),
        metric=args.get("metric") or None,
        target_value=float(args["target_value"]) if args.get("target_value") is not None else None,
        target_date=args.get("target_date") or None,
        status="active",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"plan_id": row.id, "goal": row.goal, "status": "saved"}


async def _h_web_search(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.integrations.tavily import (
        TavilyAuthError,
        TavilyAuthMissing,
        TavilyUnavailable,
        tavily_search,
    )

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return _err("query required")
    api_key = settings.tavily_api_key
    if not api_key:
        return _err("TAVILY_API_KEY not configured — web search unavailable")
    max_results = max(1, min(int(args.get("max_results") or 5), 10))
    search_depth = args.get("search_depth", "advanced")
    if search_depth not in ("basic", "advanced"):
        search_depth = "advanced"
    try:
        data = await tavily_search(
            query.strip(),
            api_key=api_key,
            max_results=max_results,
            search_depth=search_depth,
        )
    except TavilyAuthMissing as exc:
        return _err(str(exc))
    except TavilyAuthError as exc:
        return _err(f"Tavily auth error: {exc}")
    except TavilyUnavailable as exc:
        return _err(f"Tavily unavailable: {exc}")
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in data.get("results", [])
    ]
    return {
        "query": query,
        "answer": data.get("answer"),
        "results": results,
        "n": len(results),
    }


async def _h_save_research_paper(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    from lattice.integrations.research import save_paper

    title = args.get("title")
    topic = args.get("topic")
    content = args.get("content")
    if not isinstance(title, str) or not title.strip():
        return _err("title required")
    if not isinstance(topic, str) or not topic.strip():
        return _err("topic required")
    if not isinstance(content, str) or not content.strip():
        return _err("content required")
    sources = [str(s) for s in (args.get("sources") or [])]
    filename = save_paper(title=title.strip(), topic=topic.strip(), content=content.strip(), sources=sources)
    return {"filename": filename, "title": title, "topic": topic, "saved": True}


async def _h_list_research_papers(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    from lattice.integrations.research import list_papers

    topic = args.get("topic")
    papers = list_papers(topic=topic if isinstance(topic, str) and topic else None)
    return {"count": len(papers), "papers": papers}


async def _h_read_research_paper(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    from lattice.integrations.research import read_paper

    filename = args.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        return _err("filename required")
    try:
        content = read_paper(filename.strip())
        return {"filename": filename, "content": content}
    except FileNotFoundError as exc:
        return _err(str(exc))


async def _h_list_plans(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import select

    from lattice.models import Plan

    rows = list(
        (await session.execute(
            select(Plan).where(Plan.status == "active").order_by(Plan.created_at.desc())
        )).scalars().all()
    )
    return {
        "count": len(rows),
        "plans": [
            {
                "id": r.id,
                "goal": r.goal,
                "plan": r.plan,
                "metric": r.metric,
                "target_value": r.target_value,
                "target_date": r.target_date,
                "progress_note": r.progress_note,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


_MAX_MEMORY_LEN = 500
_MAX_PENDING_LEN = 300
_MAX_JOURNAL_LEN = 300


async def _h_remember(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import UserMemory

    content = str(args.get("content") or "").strip()
    if not content:
        return _err("content (non-empty string) required")
    if len(content) > _MAX_MEMORY_LEN:
        return _err(f"content too long (max {_MAX_MEMORY_LEN} chars)")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    row = UserMemory(content=content, created_at=now, updated_at=now)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "content": row.content}


async def _h_update_memory(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import UserMemory

    memory_id = args.get("id")
    if not isinstance(memory_id, int):
        return _err("id (int) required")
    content = str(args.get("content") or "").strip()
    if not content:
        return _err("content (non-empty string) required")
    if len(content) > _MAX_MEMORY_LEN:
        return _err(f"content too long (max {_MAX_MEMORY_LEN} chars)")
    row = await session.get(UserMemory, memory_id)
    if row is None:
        return _err(f"memory {memory_id} not found")
    row.content = content
    row.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    await session.commit()
    return {"id": memory_id, "content": content}


async def _h_forget(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import UserMemory

    memory_id = args.get("id")
    if not isinstance(memory_id, int):
        return _err("id (int) required")
    row = await session.get(UserMemory, memory_id)
    if row is None:
        return _err(f"memory {memory_id} not found")
    await session.delete(row)
    await session.commit()
    return {"forgot": memory_id}


async def _h_note_pending_action(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import PendingAction

    summary = str(args.get("summary") or "").strip()
    if not summary:
        return _err("summary (non-empty string) required")
    if len(summary) > _MAX_PENDING_LEN:
        return _err(f"summary too long (max {_MAX_PENDING_LEN} chars)")
    detail_raw = args.get("detail")
    detail = str(detail_raw).strip() if isinstance(detail_raw, str) and detail_raw.strip() else None
    now = datetime.now(UTC).isoformat(timespec="seconds")
    row = PendingAction(
        summary=summary,
        detail=detail,
        status="open",
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "summary": row.summary, "status": row.status}


async def _h_resolve_pending_action(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import PendingAction

    action_id = args.get("id")
    if not isinstance(action_id, int):
        return _err("id (int) required")
    outcome = args.get("outcome")
    if outcome not in ("done", "dropped"):
        return _err("outcome must be 'done' or 'dropped'")
    row = await session.get(PendingAction, action_id)
    if row is None:
        return _err(f"pending action {action_id} not found")
    row.status = outcome
    row.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    await session.commit()
    return {"id": action_id, "status": outcome}


async def _h_journal_observation(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy.exc import IntegrityError

    from lattice.models import AIJournal

    entry = str(args.get("entry") or "").strip()
    if not entry:
        return _err("entry (non-empty string) required")
    if len(entry) > _MAX_JOURNAL_LEN:
        return _err(f"entry too long (max {_MAX_JOURNAL_LEN} chars)")
    kind = args.get("kind") or "observation"
    if kind not in ("observation", "correction"):
        return _err("kind must be 'observation' or 'correction'")
    trigger_raw = args.get("trigger")
    trigger = (
        str(trigger_raw).strip() if isinstance(trigger_raw, str) and trigger_raw.strip() else None
    )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    row = AIJournal(
        entry=entry,
        kind=kind,
        trigger=trigger,
        weight=1,
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        # Exact-duplicate entry — reinforce the existing row instead of erroring.
        await session.rollback()
        existing = (
            await session.execute(select(AIJournal).where(AIJournal.entry == entry))
        ).scalar_one()
        existing.weight += 1
        existing.updated_at = now
        await session.commit()
        return {"id": existing.id, "kind": existing.kind, "weight": existing.weight}
    await session.refresh(row)
    return {"id": row.id, "kind": row.kind, "weight": row.weight}


async def _h_reinforce_journal(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import AIJournal

    journal_id = args.get("id")
    if not isinstance(journal_id, int):
        return _err("id (int) required")
    row = await session.get(AIJournal, journal_id)
    if row is None:
        return _err(f"journal entry {journal_id} not found")
    row.weight += 1
    row.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    await session.commit()
    return {"id": journal_id, "weight": row.weight}


async def _h_retire_journal(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import AIJournal

    journal_id = args.get("id")
    if not isinstance(journal_id, int):
        return _err("id (int) required")
    row = await session.get(AIJournal, journal_id)
    if row is None:
        return _err(f"journal entry {journal_id} not found")
    row.active = False
    row.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
    await session.commit()
    return {"id": journal_id, "retired": True}


# --------------------------------------------------------------------------- #
# Routine handlers (Phase B) — scheduled AI reviews + reminders
# --------------------------------------------------------------------------- #


def _routine_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "type": row.type,
        "time": f"{row.hour:02d}:{row.minute:02d}",
        "weekday_mask": row.weekday_mask,
        "chattiness": row.chattiness,
        "enabled": row.enabled,
        "instruction": row.instruction,
        "reminder_text": row.reminder_text,
        "last_run_at": row.last_run_at,
    }


async def _h_list_routines(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import Routine

    rows = (
        await session.execute(
            select(Routine).order_by(Routine.hour.asc(), Routine.minute.asc())
        )
    ).scalars().all()
    return {"count": len(rows), "items": [_routine_summary(r) for r in rows]}


async def _h_create_routine(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from pydantic import ValidationError

    from lattice.models import Routine
    from lattice.schemas.routine import RoutineIn
    from lattice.sync import scheduler

    try:
        payload = RoutineIn(**args)
    except ValidationError as exc:
        return _err(f"invalid routine: {exc.errors()[0]['msg'] if exc.errors() else exc}")

    row = Routine(
        name=payload.name.strip(),
        type=payload.type,
        hour=payload.hour,
        minute=payload.minute,
        weekday_mask=payload.weekday_mask,
        instruction=(payload.instruction or None),
        chattiness=payload.chattiness,
        reminder_text=(payload.reminder_text or None),
        enabled=payload.enabled,
        last_run_at=None,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    await scheduler.reschedule(row.id)
    return _routine_summary(row)


async def _h_update_routine(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from pydantic import ValidationError

    from lattice.models import Routine
    from lattice.schemas.routine import RoutinePatch
    from lattice.sync import scheduler

    routine_id = args.get("id")
    if not isinstance(routine_id, int):
        return _err("id (int) required")
    row = await session.get(Routine, routine_id)
    if row is None:
        return _err(f"routine {routine_id} not found")

    fields = {k: v for k, v in args.items() if k != "id"}
    try:
        patch = RoutinePatch(**fields)
    except ValidationError as exc:
        return _err(f"invalid update: {exc.errors()[0]['msg'] if exc.errors() else exc}")

    for attr, value in patch.model_dump(exclude_unset=True).items():
        if attr == "name" and isinstance(value, str):
            value = value.strip()
        setattr(row, attr, value)

    if row.type == "reminder" and not (row.reminder_text and row.reminder_text.strip()):
        return _err("reminder routines require reminder_text")
    if row.type == "ai_review" and not (row.instruction and row.instruction.strip()):
        return _err("ai_review routines require instruction")

    await session.commit()
    await session.refresh(row)
    await scheduler.reschedule(row.id)
    return _routine_summary(row)


async def _h_delete_routine(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models import Routine
    from lattice.sync import scheduler

    routine_id = args.get("id")
    if not isinstance(routine_id, int):
        return _err("id (int) required")
    row = await session.get(Routine, routine_id)
    if row is None:
        return _err(f"routine {routine_id} not found")
    await session.delete(row)
    await session.commit()
    scheduler.remove_routine_job(routine_id)
    return {"deleted": routine_id}


# --------------------------------------------------------------------------- #
# Alert rule handlers (Phase C)
# --------------------------------------------------------------------------- #

_ALERT_OPS = {"lt", "lte", "gt", "gte"}


def _alert_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "metric_name": row.metric_name,
        "operator": row.operator,
        "threshold": row.threshold,
        "label": row.label,
        "cooldown_hours": row.cooldown_hours,
        "active": row.active,
    }


async def _h_list_alerts(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models.alert import AlertRule

    rows = (
        await session.execute(select(AlertRule).order_by(AlertRule.id))
    ).scalars().all()
    return {"count": len(rows), "items": [_alert_summary(r) for r in rows]}


async def _h_create_alert(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models.alert import AlertRule

    metric_name = str(args.get("metric_name", "")).strip()
    operator = str(args.get("operator", "")).strip()
    label = str(args.get("label", "")).strip()
    if not metric_name:
        return _err("metric_name required")
    if operator not in _ALERT_OPS:
        return _err(f"operator must be one of {sorted(_ALERT_OPS)}")
    if not label:
        return _err("label required")
    try:
        threshold = float(args["threshold"])
    except (KeyError, TypeError, ValueError):
        return _err("threshold (number) required")
    cooldown_hours = args.get("cooldown_hours", 4)
    if not isinstance(cooldown_hours, int) or cooldown_hours < 1:
        return _err("cooldown_hours must be a positive integer")

    row = AlertRule(
        metric_name=metric_name,
        operator=operator,
        threshold=threshold,
        label=label,
        cooldown_hours=cooldown_hours,
        active=True,
        created_at=datetime.now(ZoneInfo(settings.timezone)).isoformat(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _alert_summary(row)


async def _h_delete_alert(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    from lattice.models.alert import AlertRule

    rule_id = args.get("id")
    if not isinstance(rule_id, int):
        return _err("id (int) required")
    row = await session.get(AlertRule, rule_id)
    if row is None:
        return _err(f"alert {rule_id} not found")
    await session.delete(row)
    await session.commit()
    return {"deleted": rule_id}


# --------------------------------------------------------------------------- #
# AI-authored algorithm handlers (Phase 2L-a)
# --------------------------------------------------------------------------- #


async def _h_create_algorithm(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name", "")
    description = args.get("description", "")
    code = args.get("code", "")
    data_requirements = args.get("data_requirements", {})
    if not isinstance(name, str) or not name:
        return _err("name is required (non-empty string)")
    if not isinstance(description, str) or not description:
        return _err("description is required")
    if not isinstance(code, str) or not code:
        return _err("code is required")
    if not isinstance(data_requirements, dict):
        return _err("data_requirements must be an object")
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return _err("name must be snake_case (lowercase letters, digits, underscores; start with letter)")
    try:
        validate_code(code)
    except ValueError as exc:
        return _err(f"code validation failed: {exc}")
    now = _now_iso()
    dr_json = json.dumps(data_requirements)
    stmt = sqlite_insert(CustomAlgorithm.__table__).values(
        name=name,
        description=description,
        code=code,
        data_requirements=dr_json,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={
            "description": stmt.excluded.description,
            "code": stmt.excluded.code,
            "data_requirements": stmt.excluded.data_requirements,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return {"name": name, "saved": True, "updated_at": now}


async def _h_run_algorithm(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name", "")
    if not isinstance(name, str) or not name:
        return _err("name is required")
    row = (
        await session.execute(select(CustomAlgorithm).where(CustomAlgorithm.name == name))
    ).scalar_one_or_none()
    if row is None:
        return _err(f"algorithm '{name}' not found — use list_algorithms to see available ones")
    try:
        requirements = json.loads(row.data_requirements)
    except json.JSONDecodeError:
        return _err("stored data_requirements is invalid JSON")
    try:
        data = await fetch_algorithm_data(session, requirements)
    except Exception as exc:  # noqa: BLE001
        return _err(f"data fetch failed: {type(exc).__name__}: {exc}")
    try:
        result = await asyncio.to_thread(execute_algorithm, row.code, data)
    except TimeoutError:
        return _err("algorithm timed out (exceeded 5 seconds)")
    except Exception as exc:  # noqa: BLE001
        return _err(f"algorithm raised {type(exc).__name__}: {exc}")
    return {"name": name, "result": result}


async def _h_list_algorithms(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    rows = list(
        (await session.execute(select(CustomAlgorithm).order_by(CustomAlgorithm.created_at.desc())))
        .scalars()
        .all()
    )
    return {
        "count": len(rows),
        "items": [
            {
                "name": r.name,
                "description": r.description,
                "data_requirements": json.loads(r.data_requirements),
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
    }


async def _h_delete_algorithm(session: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name", "")
    if not isinstance(name, str) or not name:
        return _err("name is required")
    row = (
        await session.execute(select(CustomAlgorithm).where(CustomAlgorithm.name == name))
    ).scalar_one_or_none()
    if row is None:
        return _err(f"algorithm '{name}' not found — use list_algorithms to see available ones")
    await session.delete(row)
    await session.commit()
    return {"deleted": True, "name": name}


def _summarise_card(card: DashboardCard) -> dict[str, Any]:
    try:
        spec = json.loads(card.data_source)
    except (json.JSONDecodeError, TypeError):
        spec = {}
    return {
        "id": card.id,
        "title": card.title,
        "chart_type": card.chart_type,
        "position": card.position,
        "data_source": spec,
    }


async def _h_list_dashboard_cards(
    session: AsyncSession, _args: dict[str, Any],
) -> dict[str, Any]:
    rows = list((await session.execute(
        select(DashboardCard).order_by(
            DashboardCard.position.asc(), DashboardCard.id.asc(),
        )
    )).scalars().all())
    return {"cards": [_summarise_card(r) for r in rows]}


async def _h_update_dashboard_card(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    card_id = args.get("card_id")
    if not isinstance(card_id, int):
        return _err("card_id (integer) is required")
    card = (
        await session.execute(
            select(DashboardCard).where(DashboardCard.id == card_id)
        )
    ).scalar_one_or_none()
    if card is None:
        return _err(f"card {card_id} not found — list_dashboard_cards to see ids")

    if "title" in args and args["title"]:
        card.title = str(args["title"]).strip()

    new_chart_type = args.get("chart_type") or card.chart_type
    if new_chart_type not in ("line", "bar", "table"):
        return _err("chart_type must be 'line', 'bar', or 'table'")

    try:
        existing_spec = json.loads(card.data_source)
    except (json.JSONDecodeError, TypeError):
        existing_spec = {}

    if new_chart_type in ("line", "bar"):
        merged = {
            "days": args.get("days", existing_spec.get("days", 14)),
            "series": args.get("series") or existing_spec.get("series") or [],
        }
        try:
            spec_obj = DataSourceLineBar.model_validate(merged)
        except ValidationError as exc:
            return _err(f"invalid line/bar spec: {exc.errors()[0]['msg']}")
        if not spec_obj.series:
            return _err("series cannot be empty for line/bar charts")
        for s in spec_obj.series:
            if not s.metric and s.value is None:
                return _err(
                    f"series '{s.name}' must specify either 'metric' or 'value'"
                )
        new_spec_json = spec_obj.model_dump(exclude_none=True)
    else:  # table
        merged = {
            "days": args.get("days", existing_spec.get("days", 7)),
            "metric_columns": (
                args.get("metric_columns")
                or existing_spec.get("metric_columns")
                or []
            ),
        }
        try:
            spec_obj_t = DataSourceTable.model_validate(merged)
        except ValidationError as exc:
            return _err(f"invalid table spec: {exc.errors()[0]['msg']}")
        if not spec_obj_t.metric_columns:
            return _err("metric_columns cannot be empty for table charts")
        new_spec_json = spec_obj_t.model_dump(exclude_none=True)

    card.chart_type = new_chart_type
    card.data_source = json.dumps(new_spec_json)
    await session.commit()
    await session.refresh(card)
    return {
        "updated": True,
        "card_id": card.id,
        "title": card.title,
        "chart_type": card.chart_type,
        "message": f"Updated '{card.title}'.",
    }


async def _h_delete_dashboard_card(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    card_id = args.get("card_id")
    if not isinstance(card_id, int):
        return _err("card_id (integer) is required")
    card = (
        await session.execute(
            select(DashboardCard).where(DashboardCard.id == card_id)
        )
    ).scalar_one_or_none()
    if card is None:
        return _err(f"card {card_id} not found")
    title = card.title
    await session.delete(card)
    await session.commit()
    return {
        "deleted": True,
        "card_id": card_id,
        "message": f"Removed '{title}' from the dashboard.",
    }


async def _h_render_chart(
    session: AsyncSession, args: dict[str, Any],
) -> dict[str, Any]:
    """Persist a DashboardCard. Resolves to live data on each dashboard load."""
    chart_type = args.get("chart_type")
    if chart_type not in ("line", "bar", "table"):
        return _err("chart_type must be 'line', 'bar', or 'table'")
    title = (args.get("title") or "").strip()
    if not title:
        return _err("title is required")

    if chart_type in ("line", "bar"):
        try:
            spec_obj = DataSourceLineBar.model_validate({
                "days": args.get("days", 14),
                "series": args.get("series") or [],
            })
        except ValidationError as exc:
            return _err(f"invalid line/bar spec: {exc.errors()[0]['msg']}")
        if not spec_obj.series:
            return _err("series (array) is required for line/bar charts")
        for s in spec_obj.series:
            if not s.metric and s.value is None:
                return _err(
                    f"series '{s.name}' must specify either 'metric' "
                    "(to fetch values) or 'value' (constant line)"
                )
        spec_json = spec_obj.model_dump(exclude_none=True)
    else:  # table
        try:
            spec_obj_t = DataSourceTable.model_validate({
                "days": args.get("days", 7),
                "metric_columns": args.get("metric_columns") or [],
            })
        except ValidationError as exc:
            return _err(f"invalid table spec: {exc.errors()[0]['msg']}")
        if not spec_obj_t.metric_columns:
            return _err("metric_columns (array) is required for table charts")
        spec_json = spec_obj_t.model_dump(exclude_none=True)

    # Append at the end of the dashboard.
    max_pos = (
        await session.execute(select(func.max(DashboardCard.position)))
    ).scalar()
    next_pos = (max_pos or 0) + 1

    card = DashboardCard(
        title=title,
        chart_type=chart_type,
        data_source=json.dumps(spec_json),
        position=next_pos,
        created_at=_now_iso(),
    )
    session.add(card)
    await session.commit()
    await session.refresh(card)
    return {
        "saved": True,
        "card_id": card.id,
        "title": title,
        "chart_type": chart_type,
        "message": (
            f"Saved '{title}' to the dashboard. It will refresh from live "
            "data each time the user opens the Today page."
        ),
    }


# --------------------------------------------------------------------------- #
# Dispatch table
# --------------------------------------------------------------------------- #


HANDLERS = {
    "get_today_overview": _h_get_today_overview,
    "check_data_freshness": _h_check_data_freshness,
    "get_readiness": _h_get_readiness,
    "get_advice": _h_get_advice,
    "get_work_windows": _h_get_work_windows,
    "get_training_recommendation": _h_get_training_recommendation,
    "get_sleep_window": _h_get_sleep_window,
    "set_sleep_recommendation": _h_set_sleep_recommendation,
    "get_health_targets": _h_get_health_targets,
    "set_health_targets": _h_set_health_targets,
    "get_caffeine_status": _h_get_caffeine_status,
    "get_metric": _h_get_metric,
    "get_baseline": _h_get_baseline,
    "get_calendar": _h_get_calendar,
    "get_entries": _h_get_entries,
    "list_habits": _h_list_habits,
    "get_habit_adherence": _h_get_habit_adherence,
    "log_entry": _h_log_entry,
    "delete_entry": _h_delete_entry,
    "patch_entry": _h_patch_entry,
    "check_habit": _h_check_habit,
    "create_calendar_event": _h_create_calendar_event,
    "patch_calendar_event": _h_patch_calendar_event,
    "delete_calendar_event": _h_delete_calendar_event,
    "sync_garmin": _h_sync_garmin,
    "sync_calendar": _h_sync_calendar,
    # --- analytical surface ---
    "get_quick_context": _h_get_quick_context,
    "stats_for_metric": _h_stats_for_metric,
    "stats_by_hour": _h_stats_by_hour,
    "stats_by_weekday": _h_stats_by_weekday,
    "daily_series": _h_daily_series,
    "compare_windows": _h_compare_windows,
    "correlate": _h_correlate,
    "time_of_day_distribution": _h_time_of_day_distribution,
    "stress_burden_by_zone": _h_stress_burden_by_zone,
    "list_workouts": _h_list_workouts,
    "workout_stats": _h_workout_stats,
    "last_workout": _h_last_workout,
    "sleep_pattern": _h_sleep_pattern,
    "sleep_stages_for_night": _h_sleep_stages_for_night,
    "sleep_stages_pattern": _h_sleep_stages_pattern,
    "body_battery_drop_rate": _h_body_battery_drop_rate,
    "body_battery_hourly_deltas": _h_body_battery_hourly_deltas,
    "recovery_after": _h_recovery_after,
    "busy_hours_per_day": _h_busy_hours_per_day,
    # --- trend, debt, planning↔data ---
    "trend_direction": _h_trend_direction,
    "sleep_debt": _h_sleep_debt,
    "get_initiative_metrics": _h_get_initiative_metrics,
    "save_plan": _h_save_plan,
    "list_plans": _h_list_plans,
    # --- persistent memory ---
    "remember": _h_remember,
    "update_memory": _h_update_memory,
    "forget": _h_forget,
    # --- open commitments ---
    "note_pending_action": _h_note_pending_action,
    "resolve_pending_action": _h_resolve_pending_action,
    # --- ai journal ---
    "journal_observation": _h_journal_observation,
    "reinforce_journal": _h_reinforce_journal,
    "retire_journal": _h_retire_journal,
    # --- routines (Phase B) ---
    "list_routines": _h_list_routines,
    "create_routine": _h_create_routine,
    "update_routine": _h_update_routine,
    "delete_routine": _h_delete_routine,
    # --- alert rules (Phase C) ---
    "list_alerts": _h_list_alerts,
    "create_alert": _h_create_alert,
    "delete_alert": _h_delete_alert,
    # --- AI-authored algorithms (Phase 2L-a) ---
    # NB: run_algorithm has no public schema — the model runs saved algorithms
    # via the dynamically injected algo_{name} tools, which dispatch through
    # _h_run_algorithm directly (see execute_tool). Exposing both was redundant.
    "create_algorithm": _h_create_algorithm,
    "list_algorithms": _h_list_algorithms,
    "delete_algorithm": _h_delete_algorithm,
    # --- nutrition ---
    "analyze_food": _h_analyze_food,
    "get_daily_nutrition": _h_get_daily_nutrition,
    "get_nutrition_goals": _h_get_nutrition_goals,
    "set_nutrition_goals": _h_set_nutrition_goals,
    "get_nutrition_history": _h_get_nutrition_history,
    # --- research agent ---
    "web_search": _h_web_search,
    "save_research_paper": _h_save_research_paper,
    "list_research_papers": _h_list_research_papers,
    "read_research_paper": _h_read_research_paper,
    # --- scientific analytics (F10) ---
    "sleep_regularity": _h_sleep_regularity,
    "lagged_correlation": _h_lagged_correlation,
    "detect_changepoints": _h_detect_changepoints,
    "recovery_trajectory": _h_recovery_trajectory,
    "allostatic_load": _h_allostatic_load,
    "sleep_architecture": _h_sleep_architecture,
    "training_load_response": _h_training_load_response,
    # --- dashboard cards (Phase 2L-c) ---
    "list_dashboard_cards": _h_list_dashboard_cards,
    "update_dashboard_card": _h_update_dashboard_card,
    "delete_dashboard_card": _h_delete_dashboard_card,
}

WRITE_TOOLS = {
    "log_entry", "delete_entry", "patch_entry",
    "check_habit", "create_calendar_event",
    "patch_calendar_event", "delete_calendar_event",
    "sync_garmin", "sync_calendar",
    "save_plan", "save_research_paper",
    "set_nutrition_goals", "set_sleep_recommendation", "set_health_targets",
    "remember", "update_memory", "forget",
    "note_pending_action", "resolve_pending_action",
    "journal_observation", "reinforce_journal", "retire_journal",
    "create_routine", "update_routine", "delete_routine",
    "create_alert", "delete_alert",
    "create_algorithm",
    "delete_algorithm",
    "render_chart", "update_dashboard_card", "delete_dashboard_card",
}

# Write tools where an identical repeated call within ONE turn can be the user's
# genuine intent (e.g. "log two coffees" → two identical log_entry calls). These
# are exempt from the within-turn duplicate-call guard. Every other write tool is
# idempotent or should never run twice with identical args in a single turn, so a
# repeat is treated as a model mistake (the dominant cause of duplicate calendar
# events: the model emitting create_calendar_event twice in parallel).
_DEDUP_EXEMPT_WRITES = {"log_entry"}


def _write_signature(name: str, args: dict[str, Any]) -> str:
    return name + ":" + json.dumps(args, sort_keys=True, default=str)


async def execute_tool(
    session: AsyncSession,
    name: str,
    args: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Dispatch a tool call. Returns (result, ok).

    Exceptions are caught and returned as `{error: ...}` so a misbehaving tool
    never crashes the agent loop — the LLM sees the error and can correct.
    """
    # render_chart — persists to dashboard_cards (no inline visual)
    if name == "render_chart":
        try:
            result = await _h_render_chart(session, args)
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool render_chart failed: %s", exc, exc_info=True)
            return _err(f"{type(exc).__name__}: {exc}"), False
        ok = "error" not in (result or {})
        return result, ok

    # algo_* — dynamically injected algorithm tools
    if name.startswith("algo_"):
        algo_name = name[5:]
        try:
            result = await _h_run_algorithm(session, {"name": algo_name})
        except Exception as exc:  # noqa: BLE001
            logger.warning("tool %s failed: %s", name, exc, exc_info=True)
            return _err(f"{type(exc).__name__}: {exc}"), False
        ok = "error" not in (result or {})
        return result, ok

    handler = HANDLERS.get(name)
    if handler is None:
        return _err(f"unknown tool: {name}"), False
    try:
        result = await handler(session, args)
    except Exception as exc:  # noqa: BLE001 — surface to LLM not crash
        logger.warning("tool %s failed: %s", name, exc, exc_info=True)
        return _err(f"{type(exc).__name__}: {exc}"), False
    ok = "error" not in (result or {})
    return result, ok


# --------------------------------------------------------------------------- #
# Agent loop
# --------------------------------------------------------------------------- #


async def run_agent(
    session: AsyncSession,
    *,
    history: list[dict[str, Any]],
    user_message: str,
    max_iters: int | None = None,
) -> AgentResult:
    """Run one chat turn. `history` is prior {role, content, tool_calls?} dicts.

    Persistence and session bookkeeping are the caller's responsibility
    (handled in `api/chat.py`).
    """
    iters = max_iters or settings.chat_max_iterations
    planning_ctx = await build_planning_context(session, user_message=user_message)

    # Load saved algorithms and inject them as dynamic tools
    algo_rows: list[CustomAlgorithm] = []
    try:
        algo_rows = list(
            (await session.execute(
                select(CustomAlgorithm).order_by(CustomAlgorithm.name.asc())
            )).scalars().all()
        )
    except Exception:  # noqa: BLE001 — defensive; table may not exist yet
        algo_rows = []
    algo_schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": f"algo_{r.name}",
                "description": f"[Saved algorithm] {r.description}",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        }
        for r in algo_rows
    ]
    all_tools = TOOL_SCHEMAS + algo_schemas

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(planning_context=planning_ctx)},
        *history,
        {"role": "user", "content": user_message},
    ]
    tool_records: list[ToolCallRecord] = []
    actions: list[str] = []
    # Signatures of write tool calls already executed this turn — see
    # _DEDUP_EXEMPT_WRITES. Maps signature → prior result so a duplicate call
    # returns the same result without re-executing (prevents duplicate events).
    executed_writes: dict[str, dict[str, Any]] = {}
    await check_budget(session)

    for _ in range(iters):
        completion = await chat_completion(
            messages=messages,
            tools=all_tools,
            model=pick_chat_model(user_message),
        )
        await record_usage(session, completion)
        choice = completion.choices[0]
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            reply = (msg.content or "").strip()
            reply = f9b_enforce(user_message, reply)
            return AgentResult(
                reply=reply or "(no reply)",
                tool_calls=tool_records,
                actions_taken=actions,
                finish_reason="stop",
            )

        # Append the assistant turn that contains the tool_calls. The OpenAI
        # spec requires this so the subsequent role=tool messages link back.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        # Execute every tool call from this assistant turn.
        for tc in tool_calls:
            name = tc.function.name
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}

            # Guard against duplicate writes within this turn (e.g. the model
            # emitting create_calendar_event twice in parallel). Return the
            # prior result instead of executing again so we don't create a
            # second event / row. log_entry is exempt — repeats can be intended.
            sig: str | None = None
            if name in WRITE_TOOLS and name not in _DEDUP_EXEMPT_WRITES:
                sig = _write_signature(name, args)
                if sig in executed_writes:
                    result = {
                        **executed_writes[sig],
                        "note": "duplicate call in the same turn ignored — "
                        "this action was already performed; do not repeat it",
                    }
                    tool_records.append(
                        ToolCallRecord(name=name, arguments=args, result=result, ok=True),
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    })
                    continue

            result, ok = await execute_tool(session, name, args)
            tool_records.append(
                ToolCallRecord(name=name, arguments=args, result=result, ok=ok),
            )
            if ok and name in WRITE_TOOLS:
                actions.append(name)
                if sig is not None:
                    executed_writes[sig] = result
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })
        # Continue the loop — model now sees tool results and either replies
        # or makes more tool calls.

    logger.warning("chat loop hit %d-iteration cap; tool calls so far: %s",
                   iters, [r.name for r in tool_records])

    # Force synthesis: one final completion with NO tools so the model has to
    # compose a reply from the data already in `messages` (the prior tool
    # results are still there). Far more useful than a bare tool-name dump.
    messages.append({
        "role": "system",
        "content": (
            "You have hit the tool-call iteration cap. Do NOT request more tools. "
            "Compose your best, complete answer to the user using ONLY the tool "
            "results already in this conversation. If the data is partial, say so "
            "and answer what you can — be specific, cite numbers from the results."
        ),
    })
    try:
        final = await chat_completion(
            messages=messages,
            tools=None,  # tool_choice="none" implicit when no tools
            model=pick_chat_model(user_message),
        )
        await record_usage(session, final)
        synthesis = (final.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001 — last-ditch fallback
        logger.warning("synthesis call failed: %s", exc)
        synthesis = ""

    if not synthesis:
        synthesis = (
            "Stopped after the tool-call iteration cap and couldn't synthesize "
            "a reply. Tools invoked: "
            + ", ".join(r.name for r in tool_records) + "."
        )
    synthesis = f9b_enforce(user_message, synthesis)
    return AgentResult(
        reply=synthesis,
        tool_calls=tool_records,
        actions_taken=actions,
        finish_reason="iter_cap",
    )


__all__ = [
    "AgentResult",
    "HANDLERS",
    "ToolCallRecord",
    "WRITE_TOOLS",
    "execute_tool",
    "run_agent",
]
