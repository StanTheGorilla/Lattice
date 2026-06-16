"""Chat endpoint (SPEC §5.6).

Receives a {session_id, message} pair, replays prior turns for that session_id
from the `conversations` table (up to `chat_history_turns`), runs the agent
loop, and persists every message (user, assistant, tool) back to the table.

Session idle reset: if the most recent row for this session_id is older than
`chat_session_idle_minutes`, prior turns are NOT replayed. This matches SPEC
§4.4 ("session_id resets after 30 min idle"). Clients can either reuse the
same session_id and rely on this server-side filter, or rotate the id
themselves — both work.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.integrations.deepseek import (
    DeepSeekAuthError,
    DeepSeekAuthMissing,
    DeepSeekUnavailable,
)
from lattice.llm.budget import BudgetExceeded
from lattice.llm.router import run_agent
from lattice.models import Conversation
from lattice.schemas.chat import ChatRequest, ChatResponse, ToolCallSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_auth)])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Keys we surface in the digest in priority order. Strings only; values are
# coerced to short string forms with `_format_value`.
_DIGEST_PREFERRED_KEYS: tuple[str, ...] = (
    "score", "readiness", "category",
    "duration_min", "sleep_score", "sleep_duration_min",
    "bedtime", "wake_time", "target_duration_min",
    "residual_at_bedtime_mg", "safe_for_new_cup", "last_call_minutes",
    "recommendation", "confidence",
    "status", "advisory",
    "date", "value",
)

_DIGEST_MAX_PAIRS = 4
_DIGEST_MAX_TOOLS = 6
_DIGEST_MAX_CHARS = 400


def _format_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:.1f}".rstrip("0").rstrip(".") or "0"
        return str(value)
    if isinstance(value, str):
        v = value.strip()
        return v[:60] if v else None
    return None


def _summarize_result(result: dict[str, object]) -> str:
    """Pick a few salient key=value pairs from a tool result for the digest."""
    seen: list[str] = []
    for key in _DIGEST_PREFERRED_KEYS:
        if key in result:
            formatted = _format_value(result[key])
            if formatted is not None:
                seen.append(f"{key}={formatted}")
                if len(seen) >= _DIGEST_MAX_PAIRS:
                    break
    if not seen:
        # Fall back to the first few simple scalars.
        for key, value in result.items():
            if key.startswith("_") or key in {"items", "rows"}:
                continue
            formatted = _format_value(value)
            if formatted is None:
                continue
            seen.append(f"{key}={formatted}")
            if len(seen) >= _DIGEST_MAX_PAIRS:
                break
    return ", ".join(seen)


def build_data_digest(tool_summaries: list[ToolCallSummary]) -> str | None:
    """Return a short plain-text digest of what tools surfaced this turn.

    Format: ``data consulted: <tool>(<k=v, …>); <tool>(<k=v, …>); …`` —
    truncated to `_DIGEST_MAX_CHARS`. Returns None when nothing useful was
    consulted (no successful tool calls), so the assistant row stays clean.
    """
    if not tool_summaries:
        return None
    pieces: list[str] = []
    for summary in tool_summaries[:_DIGEST_MAX_TOOLS]:
        if not summary.ok or not isinstance(summary.result, dict):
            continue
        body = _summarize_result(summary.result)
        if body:
            pieces.append(f"{summary.name}({body})")
        else:
            pieces.append(f"{summary.name}(ok)")
    if not pieces:
        return None
    text = "data consulted: " + "; ".join(pieces)
    if len(text) > _DIGEST_MAX_CHARS:
        text = text[: _DIGEST_MAX_CHARS - 1].rstrip() + "…"
    return text


def _is_within_idle_window(latest_ts: str | None) -> bool:
    """True if `latest_ts` is younger than the session idle threshold."""
    if not latest_ts:
        return False
    try:
        ts = datetime.fromisoformat(latest_ts)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime.now(UTC) - ts < timedelta(minutes=settings.chat_session_idle_minutes)


def _format_gap(latest_ts: str | None) -> str:
    """Human gap between `latest_ts` and now, e.g. '3h' or '45m' (rounded)."""
    if not latest_ts:
        return "?"
    try:
        ts = datetime.fromisoformat(latest_ts)
    except ValueError:
        return "?"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    minutes = (datetime.now(UTC) - ts).total_seconds() / 60.0
    if minutes < 60:
        return f"{round(minutes)}m"
    return f"{round(minutes / 60)}h"


async def _load_history(
    session: AsyncSession, session_id: str,
) -> list[dict[str, object]]:
    """Return the prior {role, content, tool_calls?} messages for this session.

    The full `chat_history_turns` window is replayed whether the session is live
    or resumed — letting a chat sit no longer trims context. When the latest row
    is older than the idle threshold we prefix the first retained message with a
    `[resumed after <gap>]` marker so the model knows time has passed; that is
    the only difference between a live and a resumed reload.

    Persisted as one DB row per message. We cap reload at chat_history_turns
    MESSAGES (rows) — i.e. the last N/2 exchanges (default 20 rows ≈ 10
    exchanges). Older context is fine to drop since the system prompt is rebuilt
    each turn and durable facts are kept in the user_memory table instead.
    """
    # id is the tiebreaker: timestamps are second-resolution and the user +
    # assistant rows of one turn are written back-to-back (same second) in
    # _persist_turn. Without the id key, SQLite returns same-timestamp rows in
    # an undefined order, so reverse() could place the assistant reply before
    # the user message that prompted it — scrambling the dialogue and breaking
    # follow-ups (the model can't tell which question a later "yes" answers).
    stmt = (
        select(Conversation)
        .where(Conversation.session_id == session_id)
        .order_by(Conversation.timestamp.desc(), Conversation.id.desc())
        .limit(settings.chat_history_turns)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    if not rows:
        return []

    latest_ts = rows[0].timestamp
    resumed = not _is_within_idle_window(latest_ts)

    # Reverse to chronological order for the model. Only user/assistant
    # plain-text turns are replayed — tool_call sequences from prior turns
    # are intentionally dropped because we don't persist the tool result
    # messages (they're transient), and feeding back tool_calls without
    # their tool results would violate the OpenAI message contract.
    rows.reverse()
    history: list[dict[str, object]] = []
    for row in rows:
        if row.role not in ("user", "assistant"):
            continue
        content = row.content
        # P2-3: replay the compact tool-result digest as plain text *prefixed*
        # to the assistant reply, so the model sees what data its prior reply
        # was reacting to. Plain text keeps the OpenAI message contract intact
        # (no orphan tool_call blocks that would need their matching results).
        if row.role == "assistant" and getattr(row, "data_digest", None):
            content = f"[{row.data_digest}]\n{row.content}"
        history.append({"role": row.role, "content": content})
    # Mark the resume gap on the first retained message so the model sees that
    # time has elapsed since the prior exchange (plain text — no tool blocks).
    if resumed and history:
        marker = f"[resumed after {_format_gap(latest_ts)} gap]"
        first = history[0]
        first["content"] = f"{marker} {first['content']}"
    return history


async def _persist_turn(
    session: AsyncSession,
    *,
    session_id: str,
    user_message: str,
    assistant_reply: str,
    tool_summaries: list[ToolCallSummary],
) -> None:
    """Append the user message and assistant reply (+ tool calls) to the table.

    Tool result rows are not persisted individually — they're transient. The
    assistant reply is the durable artifact. We do store the `tool_calls`
    JSON on the assistant row so a future reload reconstructs the OpenAI
    conversation shape if needed.
    """
    now = _now_iso()
    session.add(
        Conversation(
            timestamp=now,
            role="user",
            content=user_message,
            tool_calls=None,
            session_id=session_id,
        ),
    )
    tool_calls_json: str | None = None
    if tool_summaries:
        tool_calls_json = json.dumps(
            [
                {"name": t.name, "arguments": t.arguments, "ok": t.ok}
                for t in tool_summaries
            ],
        )
    digest = build_data_digest(tool_summaries)
    session.add(
        Conversation(
            timestamp=_now_iso(),
            role="assistant",
            content=assistant_reply,
            tool_calls=tool_calls_json,
            session_id=session_id,
            data_digest=digest,
        ),
    )
    await session.commit()


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    try:
        history = await _load_history(session, payload.session_id)
        result = await run_agent(
            session, history=history, user_message=payload.message,
        )
    except DeepSeekAuthMissing as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "deepseek_unconfigured",
                "message": "DEEPSEEK_API_KEY not set; chat is unavailable",
                "details": str(exc),
            },
        ) from exc
    except DeepSeekAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "deepseek_auth_failed",
                "message": "DeepSeek rejected the API key",
                "details": str(exc),
            },
        ) from exc
    except DeepSeekUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "deepseek_unavailable",
                "message": "DeepSeek transient error",
                "details": str(exc),
            },
        ) from exc
    except BudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "budget_exceeded",
                "message": (
                    f"Daily {exc.kind} token budget spent ({exc.used}/{exc.cap}). "
                    "Resets at local midnight."
                ),
                "kind": exc.kind,
                "used": exc.used,
                "cap": exc.cap,
            },
        ) from exc

    tool_summaries = [
        ToolCallSummary(
            name=r.name, arguments=r.arguments, result=r.result, ok=r.ok,
        )
        for r in result.tool_calls
    ]
    await _persist_turn(
        session,
        session_id=payload.session_id,
        user_message=payload.message,
        assistant_reply=result.reply,
        tool_summaries=tool_summaries,
    )

    return ChatResponse(
        session_id=payload.session_id,
        reply=result.reply,
        tool_calls=tool_summaries,
        actions_taken=result.actions_taken,
        finish_reason=result.finish_reason,
        history_count=len(history),
        history_limit=settings.chat_history_turns,
    )
