"""plans table — AI-created goal plans.

Revision ID: 0007_plans
Revises: 0006_planning_system
Create Date: 2026-05-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_plans"
down_revision = "0006_planning_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("plan", sa.Text, nullable=False),
        sa.Column("metric", sa.String(64), nullable=True),
        sa.Column("target_value", sa.Float, nullable=True),
        sa.Column("target_date", sa.String(10), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("progress_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("closed_at", sa.Text, nullable=True),
    )
    op.create_index("ix_plans_status", "plans", ["status"])


def downgrade() -> None:
    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_table("plans")
