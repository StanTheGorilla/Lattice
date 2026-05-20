"""HTTP client for talking to the Lattice backend.

Authenticated via the X-Bot-Token header (SPEC §5, §10). Chat is the only
endpoint the bot calls in v1; the agent on the backend side dispatches
everything else in-process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from lattice_bot.config import settings

logger = logging.getLogger(__name__)

CHAT_TIMEOUT_S = 600.0  # deep-research chats: up to 25 tool-loop iterations


@dataclass(slots=True)
class ChatReply:
    reply: str
    session_id: str
    tool_calls: list[dict[str, Any]]
    actions_taken: list[str]
    finish_reason: str


def make_client() -> httpx.AsyncClient:
    headers: dict[str, str] = {}
    if settings.bot_shared_secret:
        headers["X-Bot-Token"] = settings.bot_shared_secret
    return httpx.AsyncClient(
        base_url=settings.backend_url,
        headers=headers,
        timeout=CHAT_TIMEOUT_S,
    )


class BackendError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"backend {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


async def post_chat(
    client: httpx.AsyncClient, *, session_id: str, message: str,
) -> ChatReply:
    """POST /api/chat — returns the agent's reply.

    Raises BackendError on non-2xx. Network failures bubble up as httpx
    exceptions so the caller can decide retry policy.
    """
    response = await client.post(
        "/api/chat",
        json={"session_id": session_id, "message": message},
    )
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise BackendError(response.status_code, detail)
    data = response.json()
    return ChatReply(
        reply=data["reply"],
        session_id=data["session_id"],
        tool_calls=data.get("tool_calls", []),
        actions_taken=data.get("actions_taken", []),
        finish_reason=data.get("finish_reason", "stop"),
    )


async def get_json(client: httpx.AsyncClient, path: str) -> Any:
    """GET helper for the briefing module. Returns parsed JSON or raises BackendError."""
    response = await client.get(path)
    if response.status_code >= 400:
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise BackendError(response.status_code, detail)
    return response.json()


__all__ = ["BackendError", "ChatReply", "get_json", "make_client", "post_chat"]
