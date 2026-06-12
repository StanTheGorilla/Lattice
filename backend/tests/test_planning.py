"""Tests for the planning-system layer (profile, areas, initiatives, decisions,
ai_rules) and its integration points (F4 plumbing, LLM context injection)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.sleep_window import compute_sleep_window
from lattice.llm.prompts import build_planning_context, build_system_prompt
from lattice.models import AIRule, Area, Decision, Initiative, Profile

TZ = "Europe/Warsaw"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_profile_singleton_create(db_session: AsyncSession) -> None:
    """Inserting id=1 stores the singleton; subsequent get returns it."""
    db_session.add(Profile(
        id=1,
        birthday="2000-05-01",
        sex_at_birth="male",
        height_cm=180.0,
        weight_kg=78.0,
        chronotype="evening",
        target_sleep_min=480,
        target_wake_time="07:30",
        caffeine_cutoff_hour=12,
        updated_at=_now(),
    ))
    await db_session.commit()

    row = await db_session.get(Profile, 1)
    assert row is not None
    assert row.birthday == "2000-05-01"
    assert row.caffeine_cutoff_hour == 12
    assert row.target_wake_time == "07:30"


# --------------------------------------------------------------------------- #
# Areas / Initiatives / Decisions / Rules — basic CRUD via the ORM
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_initiative_with_area(db_session: AsyncSession) -> None:
    area = Area(
        key="health", name="Health", description="d", sort_order=0,
        archived=False, created_at=_now(),
    )
    db_session.add(area)
    await db_session.commit()
    await db_session.refresh(area)

    init = Initiative(
        area_id=area.id,
        title="Sleep 7h+ median",
        why="energy + recovery",
        target_metric="sleep_duration_min",
        target_value=420.0,
        target_date="2026-07-01",
        status="active",
        review_at="2026-06-01",
        created_at=_now(),
    )
    db_session.add(init)
    await db_session.commit()
    await db_session.refresh(init)

    assert init.id is not None
    assert init.area_id == area.id
    assert init.status == "active"


@pytest.mark.asyncio
async def test_decision_options_json(db_session: AsyncSession) -> None:
    """Options stored as JSON string in `options` column."""
    d = Decision(
        question="Switch jobs?",
        options=json.dumps(["stay", "leave", "negotiate"]),
        criteria="comp, growth, family time",
        status="open",
        created_at=_now(),
    )
    db_session.add(d)
    await db_session.commit()
    await db_session.refresh(d)

    assert d.options is not None
    parsed = json.loads(d.options)
    assert parsed == ["stay", "leave", "negotiate"]


@pytest.mark.asyncio
async def test_ai_rule_unique(db_session: AsyncSession) -> None:
    db_session.add(AIRule(
        rule="Never suggest cardio on Mondays.",
        scope="global", scope_id=None, active=True, created_at=_now(),
    ))
    await db_session.commit()

    # Duplicate should violate the unique constraint.
    db_session.add(AIRule(
        rule="Never suggest cardio on Mondays.",
        scope="global", scope_id=None, active=True, created_at=_now(),
    ))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# --------------------------------------------------------------------------- #
# LLM context block formatting
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_planning_context_empty(db_session: AsyncSession) -> None:
    """No rows -> context returns placeholder strings, never raises."""
    ctx = await build_planning_context(db_session)
    assert "no profile set" in ctx["profile_block"]
    assert "no active initiatives" in ctx["initiatives_block"]
    assert "no open decisions" in ctx["decisions_block"]
    assert "no user-defined rules" in ctx["rules_block"]


@pytest.mark.asyncio
async def test_planning_context_full(db_session: AsyncSession) -> None:
    """Profile + areas + initiatives + decisions + rules all render."""
    db_session.add(Profile(
        id=1,
        display_name="Stan",
        birthday="2000-05-01",
        sex_at_birth="male",
        target_sleep_min=480,
        target_wake_time="07:30",
        caffeine_cutoff_hour=12,
        updated_at=_now(),
    ))
    area = Area(key="health", name="Health", sort_order=0, archived=False, created_at=_now())
    db_session.add(area)
    await db_session.commit()
    await db_session.refresh(area)

    db_session.add(Initiative(
        area_id=area.id,
        title="Hit 7h sleep median",
        why="recovery",
        target_outcome="median ≥420 min by July",
        review_at="2026-06-01",
        status="active",
        created_at=_now(),
    ))
    db_session.add(Initiative(
        area_id=area.id,
        title="Run 5k under 25 min",
        status="paused",  # should NOT appear (paused != active)
        created_at=_now(),
    ))
    db_session.add(Decision(
        question="Should I switch to a polyphasic schedule?",
        area_id=area.id,
        options=json.dumps(["no", "yes 6h core + nap"]),
        deadline="2026-06-15",
        status="open",
        created_at=_now(),
    ))
    db_session.add(AIRule(
        rule="Do not suggest reducing caffeine to zero — I will not comply.",
        scope="global", scope_id=None, active=True, created_at=_now(),
    ))
    db_session.add(AIRule(
        rule="Inactive rule",
        scope="global", scope_id=None, active=False, created_at=_now(),
    ))
    await db_session.commit()

    ctx = await build_planning_context(db_session)
    assert "Stan" in ctx["profile_block"]
    assert "Health" in ctx["initiatives_block"]
    assert "Hit 7h sleep median" in ctx["initiatives_block"]
    assert "Run 5k under 25 min" not in ctx["initiatives_block"]  # paused excluded
    assert "polyphasic schedule" in ctx["decisions_block"]
    assert "Do not suggest reducing caffeine" in ctx["rules_block"]
    assert "Inactive rule" not in ctx["rules_block"]


@pytest.mark.asyncio
async def test_system_prompt_renders_with_context(db_session: AsyncSession) -> None:
    """build_system_prompt accepts a planning_context dict."""
    db_session.add(Profile(id=1, display_name="Tester", updated_at=_now()))
    await db_session.commit()
    ctx = await build_planning_context(db_session)
    prompt = build_system_prompt(planning_context=ctx)
    assert "Tester" in prompt
    assert "USER PROFILE" in prompt
    assert "ACTIVE INITIATIVES" in prompt
    assert "OPEN DECISIONS" in prompt
    assert "USER-DEFINED RULES" in prompt
    assert "ACTIVE PROTOCOLS" in prompt  # plans block baked in


# --------------------------------------------------------------------------- #
# F4 plumbing — profile drives wake time, sleep target, caffeine cutoff
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_f4_uses_profile_target_sleep_when_no_data(db_session: AsyncSession) -> None:
    """Profile.target_sleep_min overrides the computed within-range base."""
    db_session.add(Profile(id=1, target_sleep_min=540, updated_at=_now()))  # 9h
    await db_session.commit()

    out = await compute_sleep_window(
        db_session, target=date(2026, 5, 15), tz=TZ,
    )
    assert out.target_duration_min == 540.0
    assert any("configured target" in f.lower() for f in out.flags)


@pytest.mark.asyncio
async def test_f4_uses_profile_wake_time(db_session: AsyncSession) -> None:
    """Profile.target_wake_time overrides the 08:00 default when no event."""
    db_session.add(Profile(id=1, target_wake_time="06:30", updated_at=_now()))
    await db_session.commit()

    out = await compute_sleep_window(
        db_session, target=date(2026, 5, 15), tz=TZ,
    )
    wake = datetime.fromisoformat(out.wake_time).astimezone(ZoneInfo(TZ))
    assert wake.hour == 6 and wake.minute == 30


@pytest.mark.asyncio
async def test_f4_uses_profile_caffeine_cutoff(db_session: AsyncSession) -> None:
    """Profile.caffeine_cutoff_hour overrides the 14:00 default for the flag.

    Log coffee at 13:00 with cutoff=12 — should flag. With cutoff=14 (default)
    same coffee would NOT flag.
    """
    from lattice.models import Entry

    db_session.add(Profile(id=1, caffeine_cutoff_hour=12, updated_at=_now()))
    target = date(2026, 5, 15)
    zone = ZoneInfo(TZ)
    coffee_ts = datetime(target.year, target.month, target.day, 13, 0, tzinfo=zone)
    db_session.add(Entry(
        timestamp=coffee_ts.isoformat(),
        logged_at=coffee_ts.isoformat(),
        type="drink",
        data=json.dumps({"kind": "coffee", "count": 1}),
        source="test",
    ))
    await db_session.commit()

    out = await compute_sleep_window(db_session, target=target, tz=TZ)
    assert any("caffeine logged at 13:00" in f for f in out.flags)


@pytest.mark.asyncio
async def test_f4_default_cutoff_when_profile_missing(db_session: AsyncSession) -> None:
    """No profile -> 14:00 default cutoff."""
    from lattice.models import Entry

    target = date(2026, 5, 15)
    zone = ZoneInfo(TZ)
    coffee_ts = datetime(target.year, target.month, target.day, 13, 0, tzinfo=zone)
    db_session.add(Entry(
        timestamp=coffee_ts.isoformat(),
        logged_at=coffee_ts.isoformat(),
        type="drink",
        data=json.dumps({"kind": "coffee", "count": 1}),
        source="test",
    ))
    await db_session.commit()

    out = await compute_sleep_window(db_session, target=target, tz=TZ)
    # 13:00 < 14:00 default -> no flag
    assert not any("caffeine logged" in f for f in out.flags)


# --------------------------------------------------------------------------- #
# Initiative status transitions — closed_at stamping logic mirror
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_initiative_close_sets_closed_at(db_session: AsyncSession) -> None:
    """Verifies the model accepts closed_at being set independently of status
    (the API stamps it; this test just confirms the schema supports it)."""
    area = Area(key="x", name="X", sort_order=0, archived=False, created_at=_now())
    db_session.add(area)
    await db_session.commit()
    await db_session.refresh(area)

    init = Initiative(
        area_id=area.id, title="t", status="completed",
        closed_at=_now(), outcome_note="hit target",
        created_at=_now(),
    )
    db_session.add(init)
    await db_session.commit()
    await db_session.refresh(init)
    assert init.closed_at is not None
    assert init.outcome_note == "hit target"


# --------------------------------------------------------------------------- #
# Decision ordering — deadline-first, then created_at desc
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_decisions_ordered_in_context(db_session: AsyncSession) -> None:
    """Open decisions with a deadline appear before those without."""
    base = datetime.now(UTC)
    db_session.add(Decision(
        question="No deadline",
        status="open",
        created_at=base.isoformat(),
    ))
    db_session.add(Decision(
        question="Soon",
        deadline=(date.today() + timedelta(days=3)).isoformat(),
        status="open",
        created_at=(base + timedelta(seconds=1)).isoformat(),
    ))
    db_session.add(Decision(
        question="Later",
        deadline=(date.today() + timedelta(days=30)).isoformat(),
        status="open",
        created_at=(base + timedelta(seconds=2)).isoformat(),
    ))
    await db_session.commit()

    ctx = await build_planning_context(db_session)
    block = ctx["decisions_block"]
    # "Soon" must appear before "Later" must appear before "No deadline"
    soon_idx = block.find("Soon")
    later_idx = block.find("Later")
    none_idx = block.find("No deadline")
    assert 0 <= soon_idx < later_idx < none_idx
