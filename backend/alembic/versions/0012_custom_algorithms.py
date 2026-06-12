"""Add custom_algorithms table for AI-authored reusable functions.

Revision ID: 0012_custom_algorithms
Revises: 0011_user_memory
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_custom_algorithms"
down_revision = "0011_user_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_algorithms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("data_requirements", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_custom_algorithms_name", "custom_algorithms", ["name"])


def downgrade() -> None:
    op.drop_index("ix_custom_algorithms_name", table_name="custom_algorithms")
    op.drop_table("custom_algorithms")
