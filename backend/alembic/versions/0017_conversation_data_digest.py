"""Add `data_digest` column to `conversations` for compact tool-result replay.

P2-3: chat history replay drops all tool results (decision 2G-9) so on a
follow-up question the agent either re-fetches or answers without data.
Persist a short plain-text digest of what was consulted on the assistant
row, then prepend it as plain text in `_load_history` — keeps the OpenAI
message contract intact (no orphan tool_call blocks) while preserving the
context the user is reacting to.

Revision ID: 0017_conversation_data_digest
Revises: 0016_seed_ai_review_routine
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_conversation_data_digest"
down_revision = "0016_seed_ai_review_routine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("data_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("data_digest")
