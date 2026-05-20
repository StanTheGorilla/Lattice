"""SQLAlchemy ORM models for Lattice.

All tables per SPEC §4. Importing this package registers every model on the
shared `Base.metadata` used by Alembic for autogeneration.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — all models inherit from this."""


from lattice.models.alert import AlertEvent, AlertRule  # noqa: E402, F401
from lattice.models.calendar_cache import CalendarCache  # noqa: E402, F401
from lattice.models.conversation import Conversation  # noqa: E402, F401
from lattice.models.entry import Entry  # noqa: E402, F401
from lattice.models.habit import HabitCheckin, HabitDefinition  # noqa: E402, F401
from lattice.models.llm_usage import LLMUsage  # noqa: E402, F401
from lattice.models.metric import Metric  # noqa: E402, F401
from lattice.models.metric_sample import MetricSample  # noqa: E402, F401
from lattice.models.planning import (  # noqa: E402, F401
    AIRule,
    Area,
    Decision,
    Initiative,
    Plan,
    Profile,
)
from lattice.models.sleep_stage import SleepStage  # noqa: E402, F401
from lattice.models.weekly_report import WeeklyReport  # noqa: E402, F401
from lattice.models.workout import Workout  # noqa: E402, F401

__all__ = [
    "AIRule",
    "AlertEvent",
    "AlertRule",
    "Area",
    "Base",
    "CalendarCache",
    "Conversation",
    "Decision",
    "Entry",
    "HabitCheckin",
    "HabitDefinition",
    "Initiative",
    "LLMUsage",
    "Plan",
    "Metric",
    "MetricSample",
    "Profile",
    "SleepStage",
    "WeeklyReport",
    "Workout",
]
