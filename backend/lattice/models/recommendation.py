"""Single source of truth for recommendations the AI owns (Phase A).

A generalized keyed store: one row per (kind, target_date). The chat agent (or
a routine) writes the authoritative decision as a `source='ai'` row; the
deterministic functions provide a `source='formula'` fallback that is lazily
materialized on read and NEVER overwrites an existing AI row. Every surface
(website, Discord brief, chat) reads through `functions/recommendation_store`
so they cannot disagree.

`kind` keeps this open to future decisions (`daily_focus`, etc.) without a new
table — matching the existing keyed-store pattern (`custom_algorithms`,
`user_memory`, `dashboard_cards`).
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # 'ai' | 'formula'
    author: Mapped[str] = mapped_column(String(32), nullable=False)  # 'chat' | 'routine:<id>' | 'f4_seed'
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "target_date", name="uq_recommendations_kind_date"),
        Index("ix_recommendations_kind_date", "kind", "target_date"),
    )
