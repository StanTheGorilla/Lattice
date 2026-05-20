"""planning system tables — profile, areas, initiatives, decisions, ai_rules.

Adds the user-facing "spine" above raw metrics:
- profile: singleton identity + targets
- areas: life domains (Health, Work, ...)
- initiatives: current bets per area
- decisions: open queue + closed ledger
- ai_rules: explicit constraints injected into LLM system prompt

Also seeds the default set of areas so the planning page isn't empty on first
load. Users can rename/archive/add — these are starter rows, not fixed.

Revision ID: 0006_planning_system
Revises: 0005_sleep_stages
Create Date: 2026-05-15
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0006_planning_system"
down_revision = "0005_sleep_stages"
branch_labels = None
depends_on = None


DEFAULT_AREAS = [
    ("health", "Health", "Physical and mental baseline — sleep, training, recovery, mood.", 0),
    ("work", "Work", "Career, deep work, and professional output.", 1),
    ("relationships", "Relationships", "Family, partner, friends, community.", 2),
    ("learning", "Learning", "Skills, study, books, courses.", 3),
    ("creative", "Creative", "Projects, expression, side bets.", 4),
    ("finances", "Finances", "Income, savings, investments, runway.", 5),
]


def upgrade() -> None:
    # ----- profile (singleton) ----- #
    op.create_table(
        "profile",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("birthday", sa.String(length=10), nullable=True),
        sa.Column("sex_at_birth", sa.String(length=32), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("chronotype", sa.String(length=16), nullable=True),
        sa.Column("work_pattern", sa.Text(), nullable=True),
        sa.Column("health_flags", sa.Text(), nullable=True),
        sa.Column("target_sleep_min", sa.Integer(), nullable=True),
        sa.Column("target_wake_time", sa.String(length=5), nullable=True),
        sa.Column("caffeine_cutoff_hour", sa.Integer(), nullable=True),
        sa.Column("last_meal_cutoff_hour", sa.Integer(), nullable=True),
        sa.Column("screen_off_hour", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=True),
    )

    # Insert the singleton row.
    op.execute("INSERT INTO profile (id) VALUES (1)")

    # ----- areas ----- #
    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=32), nullable=False, unique=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.Text(), nullable=False),
    )

    # Seed defaults.
    now_iso = datetime.now(UTC).isoformat(timespec="seconds")
    areas_t = sa.table(
        "areas",
        sa.column("key", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.Text),
    )
    op.bulk_insert(
        areas_t,
        [
            {
                "key": key,
                "name": name,
                "description": desc,
                "sort_order": order,
                "created_at": now_iso,
            }
            for (key, name, desc, order) in DEFAULT_AREAS
        ],
    )

    # ----- initiatives ----- #
    op.create_table(
        "initiatives",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "area_id",
            sa.Integer(),
            sa.ForeignKey("areas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("target_outcome", sa.Text(), nullable=True),
        sa.Column("target_metric", sa.String(length=64), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("target_date", sa.String(length=10), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("review_at", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("closed_at", sa.Text(), nullable=True),
        sa.Column("outcome_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_initiatives_area_status", "initiatives", ["area_id", "status"],
    )
    op.create_index("ix_initiatives_status", "initiatives", ["status"])

    # ----- decisions ----- #
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "area_id",
            sa.Integer(),
            sa.ForeignKey("areas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "initiative_id",
            sa.Integer(),
            sa.ForeignKey("initiatives.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("options", sa.Text(), nullable=True),
        sa.Column("criteria", sa.Text(), nullable=True),
        sa.Column("deadline", sa.String(length=10), nullable=True),
        sa.Column("decided_at", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=True),
        sa.Column("review_at", sa.String(length=10), nullable=True),
        sa.Column("reviewed_at", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("outcome_rating", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_decisions_status", "decisions", ["status"])
    op.create_index("ix_decisions_area", "decisions", ["area_id"])
    op.create_index("ix_decisions_initiative", "decisions", ["initiative_id"])
    op.create_index("ix_decisions_review_at", "decisions", ["review_at"])

    # ----- ai_rules ----- #
    op.create_table(
        "ai_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="global"),
        sa.Column("scope_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("rule", name="uq_ai_rules_rule"),
    )
    op.create_index("ix_ai_rules_active", "ai_rules", ["active"])


def downgrade() -> None:
    op.drop_index("ix_ai_rules_active", table_name="ai_rules")
    op.drop_table("ai_rules")

    op.drop_index("ix_decisions_review_at", table_name="decisions")
    op.drop_index("ix_decisions_initiative", table_name="decisions")
    op.drop_index("ix_decisions_area", table_name="decisions")
    op.drop_index("ix_decisions_status", table_name="decisions")
    op.drop_table("decisions")

    op.drop_index("ix_initiatives_status", table_name="initiatives")
    op.drop_index("ix_initiatives_area_status", table_name="initiatives")
    op.drop_table("initiatives")

    op.drop_table("areas")
    op.drop_table("profile")
