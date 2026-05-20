"""initial schema — all tables per SPEC §4 + weekly_reports

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-13

Creates: entries, metrics, calendar_cache, conversations,
habit_definitions, habit_checkins, weekly_reports.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- entries (4.1) ---
    op.create_table(
        "entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("logged_at", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
    )
    op.create_index("ix_entries_type_timestamp", "entries", ["type", "timestamp"])
    op.create_index("ix_entries_timestamp", "entries", ["timestamp"])

    # --- metrics (4.2) ---
    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "metric_name", "timestamp", "source",
            name="uq_metrics_name_ts_src",
        ),
    )
    op.create_index("ix_metrics_name_timestamp", "metrics", ["metric_name", "timestamp"])
    op.create_index("ix_metrics_timestamp", "metrics", ["timestamp"])

    # --- calendar_cache (4.3) ---
    op.create_table(
        "calendar_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("google_event_id", sa.String(length=256), nullable=False, unique=True),
        sa.Column("start", sa.Text(), nullable=False),
        sa.Column("end", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("is_all_day", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("fetched_at", sa.Text(), nullable=False),
    )

    # --- conversations (4.4) ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=False),
    )

    # --- habits (4.5) ---
    op.create_table(
        "habit_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False, unique=True),
        sa.Column("target_per_week", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "habit_checkins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "habit_id",
            sa.Integer(),
            sa.ForeignKey("habit_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.UniqueConstraint("habit_id", "date", name="uq_habit_checkins_habit_date"),
    )

    # --- weekly_reports (decision 2A-1) ---
    op.create_table(
        "weekly_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("iso_week", sa.String(length=10), nullable=False, unique=True),
        sa.Column("generated_at", sa.Text(), nullable=False),
        sa.Column("model_used", sa.String(length=64), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
    )

    # --- enable WAL (SPEC §4) — only meaningful for SQLite ---
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql("PRAGMA journal_mode=WAL")


def downgrade() -> None:
    op.drop_table("weekly_reports")
    op.drop_table("habit_checkins")
    op.drop_table("habit_definitions")
    op.drop_table("conversations")
    op.drop_table("calendar_cache")
    op.drop_index("ix_metrics_timestamp", table_name="metrics")
    op.drop_index("ix_metrics_name_timestamp", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("ix_entries_timestamp", table_name="entries")
    op.drop_index("ix_entries_type_timestamp", table_name="entries")
    op.drop_table("entries")
