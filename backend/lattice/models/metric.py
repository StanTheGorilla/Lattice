"""Time-series numeric metrics (SPEC §4.2)."""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    extra_metadata: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)

    __table_args__ = (
        Index("ix_metrics_name_timestamp", "metric_name", "timestamp"),
        Index("ix_metrics_timestamp", "timestamp"),
        UniqueConstraint(
            "metric_name", "timestamp", "source",
            name="uq_metrics_name_ts_src",
        ),
    )
