"""Discord chat memory (SPEC §4.4). 30-day retention, pruned nightly."""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lattice.models import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user / assistant / tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # P2-3: compact plain-text summary of the data consulted this turn
    # ("data consulted: readiness=77, sleep 6h42m, …"). Replayed as plain
    # text in `_load_history` so follow-up turns retain context without
    # violating the OpenAI tool_call/tool_result message contract.
    data_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
