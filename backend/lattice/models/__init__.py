"""SQLAlchemy ORM models for Lattice.

All tables per SPEC §4. Importing this package registers every model on the
shared `Base.metadata` used by Alembic for autogeneration.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — all models inherit from this."""


from lattice.models.ai_journal import AIJournal  # noqa: E402, F401
from lattice.models.alert import AlertEvent, AlertRule  # noqa: E402, F401
from lattice.models.calendar_cache import CalendarCache  # noqa: E402, F401
from lattice.models.conversation import Conversation  # noqa: E402, F401
from lattice.models.entry import Entry  # noqa: E402, F401
from lattice.models.habit import HabitCheckin, HabitDefinition  # noqa: E402, F401
from lattice.models.llm_usage import LLMUsage  # noqa: E402, F401
from lattice.models.metric import Metric  # noqa: E402, F401
from lattice.models.metric_sample import MetricSample  # noqa: E402, F401
from lattice.models.pending_action import PendingAction  # noqa: E402, F401
from lattice.models.recommendation import Recommendation  # noqa: E402, F401
from lattice.models.planning import (  # noqa: E402, F401
    AIRule,
    Area,
    Decision,
    Initiative,
    Plan,
    Profile,
)
from lattice.models.sleep_stage import SleepStage  # noqa: E402, F401
from lattice.models.custom_algorithm import CustomAlgorithm  # noqa: E402, F401
from lattice.models.dashboard_card import DashboardCard  # noqa: E402, F401
from lattice.models.routine import Routine  # noqa: E402, F401
from lattice.models.routine_run import RoutineRun  # noqa: E402, F401
from lattice.models.user_memory import UserMemory  # noqa: E402, F401
from lattice.models.weekly_report import WeeklyReport  # noqa: E402, F401
from lattice.models.workout import Workout  # noqa: E402, F401

__all__ = [
    "AIJournal",
    "AIRule",
    "CustomAlgorithm",
    "AlertEvent",
    "AlertRule",
    "Area",
    "Base",
    "CalendarCache",
    "Conversation",
    "DashboardCard",
    "Decision",
    "Entry",
    "HabitCheckin",
    "HabitDefinition",
    "Initiative",
    "LLMUsage",
    "Plan",
    "Metric",
    "MetricSample",
    "PendingAction",
    "Profile",
    "Recommendation",
    "Routine",
    "RoutineRun",
    "SleepStage",
    "UserMemory",
    "WeeklyReport",
    "Workout",
]
