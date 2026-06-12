"""Add dashboard_cards — user-created chart cards on the Today page.

Created via the chat `render_chart` tool; resolved on every dashboard load
so values stay fresh.

Revision ID: 0013_dashboard_cards
Revises: 0012_custom_algorithms
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_dashboard_cards"
down_revision = "0012_custom_algorithms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_cards",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("chart_type", sa.String(16), nullable=False),
        sa.Column("data_source", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_dashboard_cards_position", "dashboard_cards", ["position"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_cards_position", table_name="dashboard_cards")
    op.drop_table("dashboard_cards")
