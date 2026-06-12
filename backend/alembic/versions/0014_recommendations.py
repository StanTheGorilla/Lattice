"""Add recommendations — single source of truth the AI owns (Phase A).

One row per (kind, target_date). The chat agent writes the authoritative
`source='ai'` row; F4 lazily seeds a `source='formula'` fallback that never
overwrites an AI row. Website, Discord brief, and chat all read this store so
they cannot disagree on bedtime/wake.

Revision ID: 0014_recommendations
Revises: 0013_dashboard_cards
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_recommendations"
down_revision = "0013_dashboard_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("target_date", sa.String(10), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("author", sa.String(32), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("kind", "target_date", name="uq_recommendations_kind_date"),
    )
    op.create_index(
        "ix_recommendations_kind_date", "recommendations", ["kind", "target_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendations_kind_date", table_name="recommendations")
    op.drop_table("recommendations")
