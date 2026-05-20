"""Sleep stage timeline (SPEC §4.10).

One row per stage segment within a night. Built from Garmin's `sleepLevels`
array (in `get_sleep_data`), which lists consecutive segments of awake/light/
deep/rem. Keeping each segment as its own row lets the analytical tools
answer "when does first REM happen?" and "how many wake events did I have?"
without joining anything else.
"""

from __future__ import annotations

from sqlalchemy import Float, Index, String, Text, UniqueConstraint
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class SleepStage(Base):
    __tablename__ = "sleep_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # YYYY-MM-DD of the WAKE date (so all stages of "last night" share a key).
    night_date: Mapped[str] = mapped_column(String(10), nullable=False)
    start: Mapped[str] = mapped_column(Text, nullable=False)
    end: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(String(8), nullable=False)
    duration_min: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_sleep_stages_night", "night_date"),
        Index("ix_sleep_stages_start", "start"),
        UniqueConstraint(
            "night_date", "start", "stage",
            name="uq_sleep_stages_night_start_stage",
        ),
    )
