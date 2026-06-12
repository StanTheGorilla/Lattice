"""Add `routine_runs` history table (P3-2).

A suppressed `only_notable` routine is currently invisible outside
`journalctl`. The scheduler records one row per run here (manual or
scheduled) with whether it sent/suppressed plus a short reply excerpt so
the /routines page can show the last N runs.

Revision ID: 0018_routine_runs
Revises: 0017_conversation_data_digest
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018_routine_runs"
down_revision = "0017_conversation_data_digest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routine_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("routine_id", sa.Integer(), nullable=False),
        sa.Column("fired_at", sa.Text(), nullable=False),
        sa.Column("sent", sa.Boolean(), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reply_excerpt", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_routine_runs_routine_fired",
        "routine_runs",
        ["routine_id", "fired_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_routine_runs_routine_fired", table_name="routine_runs")
    op.drop_table("routine_runs")
