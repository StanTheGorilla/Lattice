"""Intra-day Garmin samples (SPEC §4.9).

One row per measurement: heart rate per minute, stress per minute,
body battery per reading. Separate from `metrics` (daily aggregates) so
queries against intra-day data don't conflict with the daily UPSERT
unique key, and so we can prune samples independently if needed.
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class MetricSample(Base):
    __tablename__ = "metric_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_msamples_name_timestamp", "metric_name", "timestamp"),
        Index("ix_msamples_timestamp", "timestamp"),
        UniqueConstraint(
            "metric_name", "timestamp", "source",
            name="uq_msamples_name_ts_src",
        ),
    )
