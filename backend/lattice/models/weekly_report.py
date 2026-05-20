"""Weekly report storage (F7). Added in Phase 2A per decision 2A-1.

Columns:
- iso_week: e.g. "2026-W19" — unique
- generated_at: ISO 8601 with TZ offset
- model_used: e.g. "deepseek-v4-pro" or "deterministic-only"
- stats_json: serialized Stage A statistics
- summary_text: Stage B LLM prose summary (≤200 words)
"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    iso_week: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    generated_at: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
