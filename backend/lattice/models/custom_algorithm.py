"""AI-authored reusable algorithms — persisted Python functions the agent saves
for efficiency so it doesn't recompute the same logic each session."""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class CustomAlgorithm(Base):
    __tablename__ = "custom_algorithms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    data_requirements: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_custom_algorithms_name", "name"),)
