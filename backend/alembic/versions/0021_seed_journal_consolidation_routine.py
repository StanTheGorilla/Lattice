"""Seed a weekly `ai_review` routine that consolidates the AI JOURNAL.

The AI writes soft-guidance journal entries to itself (Goal 2). Over time
near-duplicates accumulate and some entries go stale. A weekly review keeps the
journal sharp: merge near-duplicates and retire guidance that no longer fits.
Routines are user-editable post-seed (paused, retimed, or the instruction
rewritten) so this is just a default.

Idempotent: if a routine with the same name already exists, do nothing —
re-running upgrade after the user renamed/deleted theirs must not resurrect
or duplicate it.

Revision ID: 0021_seed_journal_consolidation_routine
Revises: 0020_ai_journal
Create Date: 2026-06-16
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0021_seed_journal_consolidation_routine"
down_revision = "0020_ai_journal"
branch_labels = None
depends_on = None

_ROUTINE_NAME = "Weekly AI-journal review"

# Sunday-only mask: bit 6 = Sunday (Mon=0).
_SUNDAY_MASK = 1 << 6

_INSTRUCTION = (
    "Weekly review of your AI JOURNAL (self-authored soft guidance). Read all "
    "active entries shown under AI JOURNAL. Merge near-duplicates: retire the "
    "weaker ones with `retire_journal` and write a single consolidated entry "
    "with `journal_observation`. Retire stale or low-weight entries that no "
    "longer reflect the user. Keep the journal sharp and non-redundant. If "
    "nothing needs changing, say so briefly. Keep the reply under 120 words. "
    "No preamble, no sign-off."
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
                "hour": 20,
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
