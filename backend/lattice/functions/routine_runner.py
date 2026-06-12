"""Execute a single routine (Phase B).

Two paths:
  - ``reminder``  → DM ``reminder_text`` verbatim. No LLM, no tokens.
  - ``ai_review`` → run the chat agent in-process with the routine's
    ``instruction`` as the user turn, then DM the reply. For ``only_notable``
    routines the composed prompt ends with a strict notability contract: if
    nothing crosses the bar the agent replies with exactly ``NOTHING_NOTABLE``
    and the runner suppresses the DM (no message sent).

The notability sentinel is a shared module constant so the prompt builder and
the suppression check can never drift. It is matched defensively (upper/strip,
prefix, short length) so a stray period or casing doesn't leak a sentinel DM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from lattice.integrations.discord_dm import send_dm
from lattice.models import Routine

logger = logging.getLogger(__name__)

NOTABLE_SENTINEL = "NOTHING_NOTABLE"
_DISCORD_LIMIT = 1900  # leave headroom under Discord's 2000-char cap

_NOTABILITY_CONTRACT = (
    "\n\n---\n"
    "This is a silent-unless-notable check. Pull the relevant data with tools "
    "first, then judge it against a notability bar: a sustained shift versus the "
    "trailing baseline, a schedule conflict, a broken or at-risk streak, or a "
    "clear actionable signal. Routine, expected, or unchanged readings do NOT "
    f"qualify. If nothing crosses the bar, reply with EXACTLY `{NOTABLE_SENTINEL}` "
    "and nothing else — no preamble, no explanation. Otherwise give the briefing "
    "concisely (under 250 words), leading with what is notable."
)


@dataclass
class RoutineRunResult:
    routine_id: int
    type: str
    sent: bool
    suppressed: bool = False  # ai_review only_notable hit the sentinel
    detail: str = ""


def _is_sentinel(reply: str) -> bool:
    cleaned = reply.upper().strip().strip(".`*_ ")
    return cleaned.startswith(NOTABLE_SENTINEL) and len(reply.strip()) < 40


def build_ai_review_prompt(instruction: str, *, only_notable: bool) -> str:
    base = instruction.strip()
    if only_notable:
        return base + _NOTABILITY_CONTRACT
    return base


async def _send_chunks(text: str) -> bool:
    """DM `text`, splitting on Discord's char limit. True if all parts sent."""
    if not text.strip():
        return False
    ok = True
    remaining = text
    while remaining:
        chunk = remaining[:_DISCORD_LIMIT]
        remaining = remaining[_DISCORD_LIMIT:]
        ok = await send_dm(chunk) and ok
    return ok


async def run_routine(session: AsyncSession, routine: Routine) -> RoutineRunResult:
    """Run one routine now and record `last_run_at`. Caller commits."""
    routine.last_run_at = datetime.now(UTC).isoformat(timespec="seconds")

    if routine.type == "reminder":
        text = (routine.reminder_text or "").strip()
        if not text:
            return RoutineRunResult(routine.id, routine.type, sent=False,
                                    detail="empty reminder_text")
        sent = await send_dm(text)
        return RoutineRunResult(routine.id, routine.type, sent=sent)

    # ai_review
    instruction = (routine.instruction or "").strip()
    if not instruction:
        return RoutineRunResult(routine.id, routine.type, sent=False,
                                detail="empty instruction")

    only_notable = routine.chattiness == "only_notable"
    prompt = build_ai_review_prompt(instruction, only_notable=only_notable)

    # Imported here to avoid a circular import at module load (router imports
    # many functions modules; this module is imported by the scheduler/API).
    from lattice.llm.router import run_agent

    result = await run_agent(session, history=[], user_message=prompt)
    reply = (result.reply or "").strip()

    if only_notable and _is_sentinel(reply):
        logger.info("routine %s (%s): nothing notable — suppressed", routine.id, routine.name)
        return RoutineRunResult(routine.id, routine.type, sent=False, suppressed=True)

    sent = await _send_chunks(reply)
    return RoutineRunResult(routine.id, routine.type, sent=sent)


__all__ = [
    "NOTABLE_SENTINEL",
    "RoutineRunResult",
    "build_ai_review_prompt",
    "run_routine",
]
