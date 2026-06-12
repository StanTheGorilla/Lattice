"""User-created chart cards rendered on the Today page.

Created from chat via `render_chart`. `data_source` is a JSON spec that the
dashboard API resolves to live values on every load, so cards always reflect
current data rather than a frozen snapshot.
"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class DashboardCard(Base):
    __tablename__ = "dashboard_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    chart_type: Mapped[str] = mapped_column(String(16), nullable=False)
    data_source: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_dashboard_cards_position", "position"),)
