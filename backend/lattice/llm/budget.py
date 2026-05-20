"""Daily LLM token-budget gate (SPEC §7.4).

Tracks input + output tokens per local day in `llm_usage`. Calls to DeepSeek
must `check_budget(session)` before making the request and `record_usage`
after a successful call. Exceeding the cap raises `BudgetExceeded`, which
callers map to a friendly response (router.py blocks the chat reply with a
clear message; weekly_report.py falls back to its deterministic summary).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import LLMUsage

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """Today's input or output token budget is spent."""

    def __init__(self, *, kind: str, used: int, cap: int) -> None:
        super().__init__(f"daily {kind} token budget exceeded ({used}/{cap})")
        self.kind = kind
        self.used = used
        self.cap = cap


def _today() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).date().isoformat()


async def get_today_usage(session: AsyncSession) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) consumed today."""
    row = (
        await session.execute(select(LLMUsage).where(LLMUsage.date == _today()))
    ).scalar_one_or_none()
    if row is None:
        return 0, 0
    return int(row.input_tokens), int(row.output_tokens)


async def check_budget(session: AsyncSession) -> None:
    """Raise BudgetExceeded if today's usage is at or past either cap."""
    used_in, used_out = await get_today_usage(session)
    if used_in >= settings.daily_token_budget_input:
        raise BudgetExceeded(
            kind="input", used=used_in, cap=settings.daily_token_budget_input,
        )
    if used_out >= settings.daily_token_budget_output:
        raise BudgetExceeded(
            kind="output", used=used_out, cap=settings.daily_token_budget_output,
        )


def _extract_usage(completion: Any) -> tuple[int, int]:
    """Pull token counts off an openai ChatCompletion object."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(
        getattr(usage, "completion_tokens", 0) or 0,
    )


async def record_usage(session: AsyncSession, completion: Any) -> None:
    """UPSERT today's token totals from a completion response."""
    input_tokens, output_tokens = _extract_usage(completion)
    if input_tokens == 0 and output_tokens == 0:
        return
    today = _today()
    stmt = sqlite_insert(LLMUsage.__table__).values(
        date=today, input_tokens=input_tokens, output_tokens=output_tokens,
    ).on_conflict_do_update(
        index_elements=["date"],
        set_={
            "input_tokens": LLMUsage.__table__.c.input_tokens + input_tokens,
            "output_tokens": LLMUsage.__table__.c.output_tokens + output_tokens,
        },
    )
    await session.execute(stmt)
    await session.commit()


__all__ = [
    "BudgetExceeded",
    "check_budget",
    "get_today_usage",
    "record_usage",
]
