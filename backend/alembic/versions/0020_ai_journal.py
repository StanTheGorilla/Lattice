"""Add ai_journal table — self-authored soft-guidance store.

Revision ID: 0020_ai_journal
Revises: 0019_pending_actions
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020_ai_journal"
down_revision = "0019_pending_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entry", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="observation"),
        sa.Column("trigger", sa.Text(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("entry", name="uq_ai_journal_entry"),
    )
    op.create_index("ix_ai_journal_active", "ai_journal", ["active"])


def downgrade() -> None:
    op.drop_index("ix_ai_journal_active", table_name="ai_journal")
    op.drop_table("ai_journal")
