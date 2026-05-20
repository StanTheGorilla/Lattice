"""Garmin-synced workout activities (SPEC §4.8).

Distinct from user-logged `entries.type='workout_manual'`. Each row is one
Garmin activity (run, ride, strength session, etc.), keyed by Garmin's stable
activity id so re-syncs are idempotent.
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class Workout(Base):
    __tablename__ = "workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    garmin_activity_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True,
    )
    start: Mapped[str] = mapped_column(Text, nullable=False)
    duration_min: Mapped[float] = mapped_column(Float, nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_effect: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_metadata: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)

    __table_args__ = (
        Index("ix_workouts_start", "start"),
        Index("ix_workouts_kind_start", "kind", "start"),
    )
