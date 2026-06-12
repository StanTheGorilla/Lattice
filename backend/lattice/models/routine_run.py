"""Routine run history (P3-2).

One row per scheduled or manual routine execution. Captures whether the DM
was sent (or suppressed by the `only_notable` sentinel) plus a short reply
excerpt so the /routines page can show recent activity without surfacing
the full LLM output.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class RoutineRun(Base):
    __tablename__ = "routine_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routine_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fired_at: Mapped[str] = mapped_column(Text, nullable=False)
    sent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reply_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_routine_runs_routine_fired", "routine_id", "fired_at"),
    )
