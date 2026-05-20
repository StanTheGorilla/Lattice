"""Google Calendar snapshot cache (SPEC §4.3)."""

from __future__ import annotations

from sqlalchemy import Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class CalendarCache(Base):
    __tablename__ = "calendar_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    google_event_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    start: Mapped[str] = mapped_column(Text, nullable=False)
    end: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_all_day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False)
