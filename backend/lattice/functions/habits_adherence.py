"""F8 — Habit Adherence (SPEC §6).

Per-habit, pure SQL-then-Python:
  - current_streak: consecutive days ending today with completed=1
  - longest_streak: longest run of completed=1 days, ever
  - week_completion_pct: last 7 days completion / target_per_week × 100, capped 100
  - period_completion_pct: completed days in [from, to] / total days in window × 100
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.models import HabitCheckin, HabitDefinition
from lattice.schemas.functions import HabitAdherence, HabitAdherenceOutput


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _current_streak(today: date, completed_dates: set[date]) -> int:
    streak = 0
    cursor = today
    while cursor in completed_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _longest_streak(completed_dates: set[date]) -> int:
    if not completed_dates:
        return 0
    ordered = sorted(completed_dates)
    longest = 1
    current = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


async def compute_habit_adherence(
    session: AsyncSession,
    *,
    from_: date,
    to: date,
    today: date,
) -> HabitAdherenceOutput:
    defs = (
        await session.execute(
            select(HabitDefinition).where(HabitDefinition.active.is_(True)),
        )
    ).scalars().all()

    items: list[HabitAdherence] = []
    for d in defs:
        rows = (
            await session.execute(
                select(HabitCheckin).where(HabitCheckin.habit_id == d.id),
            )
        ).scalars().all()
        completed_dates = {
            _parse_date(r.date) for r in rows if r.completed
        }
        # Period filter
        period_total_days = (to - from_).days + 1
        period_completed = sum(
            1 for cd in completed_dates if from_ <= cd <= to
        )
        period_pct = (
            (period_completed / period_total_days) * 100.0
            if period_total_days > 0 else 0.0
        )
        # Week (last 7 days ending `today`).
        week_start = today - timedelta(days=6)
        week_completed = sum(
            1 for cd in completed_dates if week_start <= cd <= today
        )
        target = max(d.target_per_week, 1)
        week_pct = min(100.0, (week_completed / target) * 100.0)

        items.append(
            HabitAdherence(
                habit_id=d.id,
                name=d.name,
                target_per_week=d.target_per_week,
                current_streak_days=_current_streak(today, completed_dates),
                longest_streak_days=_longest_streak(completed_dates),
                week_completion_pct=round(week_pct, 1),
                period_completion_pct=round(period_pct, 1),
            )
        )

    return HabitAdherenceOutput(
        from_=from_.isoformat(),
        to=to.isoformat(),
        items=items,
    )


__all__ = ["compute_habit_adherence"]
