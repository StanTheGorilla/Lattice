"""Phase A — single source of truth for sleep recommendations.

The headline invariant: a deterministic `formula` seed must NEVER overwrite an
AI decision. If it could, the website/brief would silently clobber what the
chat agent concluded — the exact "out of sync" pain this store resolves.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from lattice.functions.recommendation_store import (
    SLEEP_KIND,
    get_active_sleep_recommendation,
    set_sleep_recommendation,
    tonight_target_date,
)
from lattice.models import Recommendation

TZ = "Europe/Warsaw"
TARGET = date(2026, 6, 3)


def test_tonight_target_date_is_today_local() -> None:
    assert tonight_target_date(TZ) == datetime.now(ZoneInfo(TZ)).date()


@pytest.mark.asyncio
async def test_first_read_seeds_a_formula_row(db_session) -> None:
    rec = await get_active_sleep_recommendation(db_session, target=TARGET, tz=TZ)
    assert rec.source == "formula"
    assert rec.author == "f4_seed"
    assert rec.bedtime and rec.wake_time
    # exactly one row persisted for this (kind, date)
    rows = (
        await db_session.execute(
            select(Recommendation).where(
                Recommendation.kind == SLEEP_KIND,
                Recommendation.target_date == TARGET.isoformat(),
            )
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_formula_seed_never_overwrites_ai_row(db_session) -> None:
    # 1. First read seeds a formula row (F4 fallback bedtime).
    seeded = await get_active_sleep_recommendation(db_session, target=TARGET, tz=TZ)
    assert seeded.source == "formula"

    # 2. The AI concludes a DIFFERENT bedtime and persists it.
    ai = await set_sleep_recommendation(
        db_session,
        target=TARGET,
        tz=TZ,
        bedtime="23:15",
        wake_time="07:00",
        target_duration_min=None,
        rationale="early meeting tomorrow",
        author="chat",
    )
    assert ai.source == "ai"
    assert ai.bedtime.endswith("23:15:00+02:00")
    assert ai.wake_time.endswith("07:00:00+02:00")
    # duration computed from the interval (23:15 -> 07:00 == 465 min)
    assert ai.target_duration_min == pytest.approx(465.0)

    # 3. A subsequent read returns the AI row verbatim — NOT a fresh F4 seed.
    after = await get_active_sleep_recommendation(db_session, target=TARGET, tz=TZ)
    assert after.source == "ai"
    assert after.author == "chat"
    assert after.bedtime == ai.bedtime
    assert after.rationale == "early meeting tomorrow"

    # Still exactly one row — UPSERT, not duplicate.
    rows = (
        await db_session.execute(
            select(Recommendation).where(
                Recommendation.kind == SLEEP_KIND,
                Recommendation.target_date == TARGET.isoformat(),
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "ai"


@pytest.mark.asyncio
async def test_ai_after_midnight_bedtime_rolls_to_next_day(db_session) -> None:
    # An after-midnight bedtime (e.g. 00:30) belongs to target+1, while the
    # evening wake stays the morning after. Guards date-semantics drift.
    rec = await set_sleep_recommendation(
        db_session,
        target=TARGET,
        tz=TZ,
        bedtime="00:30",
        wake_time="08:00",
        target_duration_min=None,
        rationale=None,
        author="chat",
    )
    assert rec.bedtime.startswith("2026-06-04T00:30")
    assert rec.wake_time.startswith("2026-06-04T08:00")
