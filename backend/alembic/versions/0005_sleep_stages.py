"""sleep_stages table — per-night stage timeline (SPEC §4.10)

Revision ID: 0005_sleep_stages
Revises: 0004_metric_samples
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_sleep_stages"
down_revision = "0004_metric_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sleep_stages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("night_date", sa.String(length=10), nullable=False),
        sa.Column("start", sa.Text(), nullable=False),
        sa.Column("end", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(length=8), nullable=False),
        sa.Column("duration_min", sa.Float(), nullable=False),
        sa.UniqueConstraint(
            "night_date", "start", "stage",
            name="uq_sleep_stages_night_start_stage",
        ),
    )
    op.create_index("ix_sleep_stages_night", "sleep_stages", ["night_date"])
    op.create_index("ix_sleep_stages_start", "sleep_stages", ["start"])


def downgrade() -> None:
    op.drop_index("ix_sleep_stages_start", table_name="sleep_stages")
    op.drop_index("ix_sleep_stages_night", table_name="sleep_stages")
    op.drop_table("sleep_stages")
