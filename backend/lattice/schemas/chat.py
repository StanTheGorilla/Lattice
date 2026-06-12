"""Chat endpoint schemas (SPEC §5.6).

Visual rendering moved to dashboard cards in Phase 2L-c — the chat agent's
`render_chart` tool persists to the `dashboard_cards` table; the web UI
loads them from `/api/dashboard/cards`. The chat response itself is now
text + tool-call metadata only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(
        ...,
        description=(
            "Client-managed session id. Reuse it across turns; rotate after "
            "30 min idle (SPEC §4.4). Any string up to 64 chars."
        ),
        max_length=64,
        min_length=1,
    )
    message: str = Field(..., min_length=1, max_length=4000)


class ToolCallSummary(BaseModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    ok: bool


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_calls: list[ToolCallSummary] = Field(default_factory=list)
    actions_taken: list[str] = Field(default_factory=list)
    finish_reason: str = "stop"


__all__ = ["ChatRequest", "ChatResponse", "ToolCallSummary"]
