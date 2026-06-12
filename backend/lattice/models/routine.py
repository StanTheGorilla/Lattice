"""User-configurable scheduled routines (Phase B).

Replaces the three hardcoded Discord briefs. A routine is one of:

  - ``reminder``  : at the scheduled time, DM ``reminder_text`` verbatim. No LLM.
  - ``ai_review`` : run the chat agent in-process with ``instruction`` as the
    user turn, then DM the reply. ``chattiness`` controls whether it always
    speaks (``always``) or stays silent unless something crosses a notability
    bar (``only_notable`` — the agent replies with a sentinel that the runner
    suppresses).

``weekday_mask`` is a 7-bit int (bit 0 = Monday … bit 6 = Sunday); default 127
means every day. Scheduling lives backend-side in ``sync/scheduler.py`` (the
backend owns the DB, the agent loop, and can DM directly via ``discord_dm``).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base

ALL_WEEKDAYS = 127  # 0b1111111 — Mon..Sun


class Routine(Base):
    __tablename__ = "routines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'ai_review'|'reminder'
    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    weekday_mask: Mapped[int] = mapped_column(
        Integer, nullable=False, default=ALL_WEEKDAYS,
    )
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    chattiness: Mapped[str] = mapped_column(
        String(16), nullable=False, default="always",  # 'always'|'only_notable'
    )
    reminder_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
