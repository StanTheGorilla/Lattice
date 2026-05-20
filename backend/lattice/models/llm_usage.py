"""Daily LLM token usage (SPEC §7.4)."""

from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class LLMUsage(Base):
    __tablename__ = "llm_usage"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
