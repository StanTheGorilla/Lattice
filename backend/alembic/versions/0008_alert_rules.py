"""alert_rules and alert_events tables.

Revision ID: 0008_alert_rules
Revises: 0007_plans
Create Date: 2026-05-17
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_alert_rules"
down_revision = "0007_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("operator", sa.String(4), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("cooldown_hours", sa.Integer, nullable=False, server_default="4"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_alert_rules_active", "alert_rules", ["active"])

    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.Integer, nullable=False),
        sa.Column("fired_at", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
    )
    op.create_index("ix_alert_events_rule_fired", "alert_events", ["rule_id", "fired_at"])


def downgrade() -> None:
    op.drop_index("ix_alert_events_rule_fired", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_index("ix_alert_rules_active", table_name="alert_rules")
    op.drop_table("alert_rules")
