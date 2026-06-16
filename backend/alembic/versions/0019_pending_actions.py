"""Add pending_actions table — durable open-commitments store.

Revision ID: 0019_pending_actions
Revises: 0018_routine_runs
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019_pending_actions"
down_revision = "0018_routine_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_pending_actions_status", "pending_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_pending_actions_status", table_name="pending_actions")
    op.drop_table("pending_actions")
