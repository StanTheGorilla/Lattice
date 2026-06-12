"""Add index on conversations.session_id.

Revision ID: 0010_conversation_session_index
Revises: 0009_nutrition_goals
Create Date: 2026-05-20
"""

from __future__ import annotations

from alembic import op

revision = "0010_conversation_session_index"
down_revision = "0009_nutrition_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_session_id",
        "conversations",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_session_id", table_name="conversations")
