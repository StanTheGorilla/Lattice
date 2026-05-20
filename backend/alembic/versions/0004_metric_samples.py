"""metric_samples table — intra-day Garmin samples (SPEC §4.9)

Revision ID: 0004_metric_samples
Revises: 0003_workouts
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_metric_samples"
down_revision = "0003_workouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metric_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.UniqueConstraint(
            "metric_name", "timestamp", "source",
            name="uq_msamples_name_ts_src",
        ),
    )
    op.create_index(
        "ix_msamples_name_timestamp", "metric_samples", ["metric_name", "timestamp"],
    )
    op.create_index("ix_msamples_timestamp", "metric_samples", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_msamples_timestamp", table_name="metric_samples")
    op.drop_index("ix_msamples_name_timestamp", table_name="metric_samples")
    op.drop_table("metric_samples")
