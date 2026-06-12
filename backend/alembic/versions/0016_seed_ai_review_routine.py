"""Seed a weekly `ai_review` routine that revisits AI-owned health targets.

V-4 of the versatility rework: the AI sets personalized sleep/caffeine
targets via `functions/health_targets.py` (stored in `recommendations` with
the global `target_date='*'` sentinel). Those should be revisited
periodically against fresh data — once a week is plenty for a metric that
drifts slowly. Routines are user-editable post-seed (paused, retimed, or
the instruction rewritten) so this is just a default.

Idempotent: if a routine with the same name already exists, do nothing —
re-running upgrade after the user renamed/deleted theirs must not resurrect
or duplicate it.

Revision ID: 0016_seed_ai_review_routine
Revises: 0015_routines
Create Date: 2026-06-12
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0016_seed_ai_review_routine"
down_revision = "0015_routines"
branch_labels = None
depends_on = None

_ROUTINE_NAME = "Weekly health-target review"
_ALL_WEEKDAYS = 127

# Sunday-only mask: bit 6 = Sunday (Mon=0).
_SUNDAY_MASK = 1 << 6

_INSTRUCTION = (
    "Weekly review of my personalized health targets. Use "
    "`get_health_targets` to read the current sleep floor/ceiling, daily "
    "caffeine cap, bedtime caffeine residual, and caffeine cutoff hour. "
    "Then pull the last 2-3 weeks of data with tools (sleep durations, HRV "
    "trend, recent caffeine pattern + how it correlated with sleep). Decide "
    "whether any target should move — and if it should, call "
    "`set_health_targets` with the updated value(s) and a one-sentence "
    "rationale that cites the data. If nothing should change, say so "
    "briefly and explain why current targets still fit. Keep the reply "
    "under 200 words. No preamble, no sign-off."
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT id FROM routines WHERE name = :name LIMIT 1"),
        {"name": _ROUTINE_NAME},
    ).first()
    if existing is not None:
        return

    now = datetime.now(UTC).isoformat(timespec="seconds")
    routines = sa.table(
        "routines",
        sa.column("name", sa.String),
        sa.column("type", sa.String),
        sa.column("hour", sa.Integer),
        sa.column("minute", sa.Integer),
        sa.column("weekday_mask", sa.Integer),
        sa.column("instruction", sa.Text),
        sa.column("chattiness", sa.String),
        sa.column("reminder_text", sa.Text),
        sa.column("enabled", sa.Boolean),
        sa.column("last_run_at", sa.Text),
        sa.column("created_at", sa.Text),
    )
    op.bulk_insert(
        routines,
        [
            {
                "name": _ROUTINE_NAME,
                "type": "ai_review",
                "hour": 19,
                "minute": 0,
                "weekday_mask": _SUNDAY_MASK,
                "instruction": _INSTRUCTION,
                "chattiness": "only_notable",
                "reminder_text": None,
                "enabled": True,
                "last_run_at": None,
                "created_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM routines WHERE name = :name").bindparams(
            name=_ROUTINE_NAME,
        ),
    )
