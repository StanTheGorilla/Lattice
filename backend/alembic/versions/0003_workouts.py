"""workouts table — Garmin-synced activities (SPEC §4.8)

Revision ID: 0003_workouts
Revises: 0002_llm_usage
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_workouts"
down_revision = "0002_llm_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workouts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "garmin_activity_id", sa.String(length=64), nullable=False, unique=True,
        ),
        sa.Column("start", sa.Text(), nullable=False),
        sa.Column("duration_min", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Float(), nullable=True),
        sa.Column("max_hr", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=True),
        sa.Column("training_effect", sa.Float(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
    )
    op.create_index("ix_workouts_start", "workouts", ["start"])
    op.create_index("ix_workouts_kind_start", "workouts", ["kind", "start"])


def downgrade() -> None:
    op.drop_index("ix_workouts_kind_start", table_name="workouts")
    op.drop_index("ix_workouts_start", table_name="workouts")
    op.drop_table("workouts")
