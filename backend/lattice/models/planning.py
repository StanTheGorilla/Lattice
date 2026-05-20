"""Planning system — profile, areas of life, initiatives, decisions, AI rules.

The "spine" of personal optimization. Profile is identity + targets. Areas are
the fixed surface of life domains. Initiatives are current bets inside areas.
Decisions are first-class — open queue + closed ledger. AI rules are explicit
constraints injected into the LLM system prompt.

SPEC §4.11.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class Profile(Base):
    """Singleton user profile (id == 1 by convention).

    Every field is nullable so the UI can be filled in progressively. The
    accessor in `lattice.functions.profile` returns an empty defaults dict
    when the row is missing rather than 404-ing.
    """

    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identity
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    birthday: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    sex_at_birth: Mapped[str | None] = mapped_column(String(32), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Rhythm + lifestyle
    chronotype: Mapped[str | None] = mapped_column(String(16), nullable=True)  # morning/neutral/evening
    work_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Health context (free text, comma-separated tags + notes)
    health_flags: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Targets (used by F4 / F5 / advisor)
    target_sleep_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_wake_time: Mapped[str | None] = mapped_column(String(5), nullable=True)  # HH:MM
    caffeine_cutoff_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_meal_cutoff_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_off_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Nutrition macro goals (daily targets)
    calorie_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g_goal: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g_goal: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Area(Base):
    """A life domain (Health, Work, Relationships, etc.).

    The user defines a small fixed set; initiatives + decisions hang off areas.
    `key` is a stable slug used by the LLM context to refer to the area
    without leaking the display name (which the user may rename).
    """

    __tablename__ = "areas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # #rrggbb
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class Initiative(Base):
    """A current bet within an area.

    Not OKRs. More like "what I'm working on right now in this area." Has a
    loose target (free text) and/or a measurable target tied to a tracked
    metric, plus a review_at date to force re-evaluation.
    """

    __tablename__ = "initiatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    area_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("areas.id", ondelete="CASCADE"), nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # active / paused / completed / abandoned
    review_at: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    closed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_initiatives_area_status", "area_id", "status"),
        Index("ix_initiatives_status", "status"),
    )


class Decision(Base):
    """A first-class decision in the planning system.

    Open decisions sit in a queue. Closed decisions move to the ledger and get
    a review_at date. Reviewed decisions become learning material for the AI.
    """

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    area_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("areas.id", ondelete="SET NULL"), nullable=True,
    )
    initiative_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("initiatives.id", ondelete="SET NULL"), nullable=True,
    )

    options: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(10), nullable=True)

    decided_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5

    review_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    # open / decided / reviewed / abandoned

    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_decisions_status", "status"),
        Index("ix_decisions_area", "area_id"),
        Index("ix_decisions_initiative", "initiative_id"),
        Index("ix_decisions_review_at", "review_at"),
    )


class Plan(Base):
    """An AI-created goal plan.

    User states a goal in chat; the bot researches the data and writes a
    concrete plan (specific actions, tracked metric, target). Stored here so
    the /plan page can display it and the daily review can reference it.
    """

    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[str] = mapped_column(Text, nullable=False)  # AI-written plan text
    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # active / completed / abandoned
    progress_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    closed_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_plans_status", "status"),)


class AIRule(Base):
    """Explicit rules the AI must respect.

    Injected verbatim into the system prompt under "USER-DEFINED RULES". Scope
    can be global (always), or tied to an area / initiative (only when context
    is relevant). The LLM is told to refuse to violate active rules.
    """

    __tablename__ = "ai_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    # global / area / initiative
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("rule", name="uq_ai_rules_rule"),
        Index("ix_ai_rules_active", "active"),
    )
