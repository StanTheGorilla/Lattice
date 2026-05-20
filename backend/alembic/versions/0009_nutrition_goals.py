"""Add nutrition macro goal columns to profile.

Revision ID: 0009_nutrition_goals
Revises: 0008_alert_rules
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_nutrition_goals"
down_revision = "0008_alert_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.add_column(sa.Column("calorie_goal", sa.Float(), nullable=True))
        batch.add_column(sa.Column("protein_g_goal", sa.Float(), nullable=True))
        batch.add_column(sa.Column("carbs_g_goal", sa.Float(), nullable=True))
        batch.add_column(sa.Column("fat_g_goal", sa.Float(), nullable=True))
        batch.add_column(sa.Column("fiber_g_goal", sa.Float(), nullable=True))
        batch.add_column(sa.Column("sugar_g_goal", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profile") as batch:
        batch.drop_column("sugar_g_goal")
        batch.drop_column("fiber_g_goal")
        batch.drop_column("fat_g_goal")
        batch.drop_column("carbs_g_goal")
        batch.drop_column("protein_g_goal")
        batch.drop_column("calorie_goal")
