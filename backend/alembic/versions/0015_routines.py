"""Add routines + seed three defaults reproducing the old briefs (Phase B).

The three hardcoded Discord briefs (07:30 morning, 20:00 day-review, 21:00
evening) are deleted from the bot. To lose nothing, this migration seeds three
equivalent routines the owner can edit or disable. Per the "AI owns it" rework
all three are `ai_review` routines that read the single-source-of-truth
recommendation store, so they can no longer disagree with chat.

Revision ID: 0015_routines
Revises: 0014_recommendations
Create Date: 2026-06-03
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0015_routines"
down_revision = "0014_recommendations"
branch_labels = None
depends_on = None

_ALL_WEEKDAYS = 127

_MORNING_INSTRUCTION = (
    "Good morning. Give me a tight morning brief for today. Pull the data with "
    "tools first: today's readiness score, last night's sleep, my top work "
    "window, the training recommendation, and my first calendar event of the "
    "day. Keep it to about five short lines with specific numbers. No preamble, "
    "no sign-off."
)

_DAY_REVIEW_INSTRUCTION = (
    "Daily review time. Analyse today and give me two short sections:\n\n"
    "**Positives** — what went well today based on the data (metrics, habits, "
    "sleep, energy, training, or anything else relevant). Be specific with numbers.\n\n"
    "**Watch out for / avoid** — what the data suggests I should be careful about "
    "or avoid tomorrow. Reference active plans where relevant.\n\n"
    "Use tools to pull today's data first. Keep the whole reply under 300 words. "
    "No preamble, no sign-off."
)

_EVENING_INSTRUCTION = (
    "Evening wind-down brief. Pull today's data with tools first: what I logged "
    "today, tonight's sleep window (use get_sleep_window for the bedtime/wake the "
    "rest of the app shows), caffeine last-call status, and any daily habits I "
    "haven't checked off yet. Keep it to about five short lines, specific. No "
    "preamble, no sign-off."
)


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=False),
        sa.Column("weekday_mask", sa.Integer(), nullable=False, server_default="127"),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("chattiness", sa.String(16), nullable=False, server_default="always"),
        sa.Column("reminder_text", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )

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
                "name": "Morning brief",
                "type": "ai_review",
                "hour": 7,
                "minute": 30,
                "weekday_mask": _ALL_WEEKDAYS,
                "instruction": _MORNING_INSTRUCTION,
                "chattiness": "always",
                "reminder_text": None,
                "enabled": True,
                "last_run_at": None,
                "created_at": now,
            },
            {
                "name": "Day review",
                "type": "ai_review",
                "hour": 20,
                "minute": 0,
                "weekday_mask": _ALL_WEEKDAYS,
                "instruction": _DAY_REVIEW_INSTRUCTION,
                "chattiness": "always",
                "reminder_text": None,
                "enabled": True,
                "last_run_at": None,
                "created_at": now,
            },
            {
                "name": "Evening brief",
                "type": "ai_review",
                "hour": 21,
                "minute": 0,
                "weekday_mask": _ALL_WEEKDAYS,
                "instruction": _EVENING_INSTRUCTION,
                "chattiness": "always",
                "reminder_text": None,
                "enabled": True,
                "last_run_at": None,
                "created_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("routines")
