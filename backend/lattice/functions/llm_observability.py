"""LLM usage observability (P3-1).

Aggregates the daily `llm_usage` token rows into a small report for the web
UI: per-day input/output tokens with a rough cost estimate plus a window
total. No global state — takes a session + params like every functions/ module.

Cost is an *estimate*. DeepSeek bills per-model and distinguishes cache hits
from misses; `llm_usage` only stores summed input/output tokens per day, so we
apply flat published cache-miss rates (USD per million tokens). The numbers are
indicative, not an invoice.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.models import LLMUsage

# Published DeepSeek cache-miss rates (USD per 1M tokens), used only for the
# rough estimate above. Kept here so the single place to update prices is
# obvious if DeepSeek changes them.
_INPUT_USD_PER_MTOK = 0.27
_OUTPUT_USD_PER_MTOK = 1.10


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * _INPUT_USD_PER_MTOK
        + output_tokens / 1_000_000 * _OUTPUT_USD_PER_MTOK,
        4,
    )


async def get_llm_usage_summary(
    session: AsyncSession,
    *,
    days: int = 30,
) -> dict[str, Any]:
    """Return per-day token usage + cost estimate over the trailing `days`.

    Shape:
        {
          "days": [{date, input_tokens, output_tokens, total_tokens, est_cost_usd}],
          "totals": {input_tokens, output_tokens, total_tokens, est_cost_usd},
          "input_usd_per_mtok": ..., "output_usd_per_mtok": ...,
        }
    Days with no recorded usage are omitted (the table only has rows for days
    the agent ran).
    """
    days = max(1, min(days, 365))
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    cutoff = (today - timedelta(days=days - 1)).isoformat()

    rows = list(
        (
            await session.execute(
                select(LLMUsage)
                .where(LLMUsage.date >= cutoff)
                .order_by(LLMUsage.date.desc()),
            )
        )
        .scalars()
        .all()
    )

    day_items: list[dict[str, Any]] = []
    total_in = 0
    total_out = 0
    for row in rows:
        in_tok = int(row.input_tokens)
        out_tok = int(row.output_tokens)
        total_in += in_tok
        total_out += out_tok
        day_items.append(
            {
                "date": row.date,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "est_cost_usd": _estimate_cost_usd(in_tok, out_tok),
            },
        )

    return {
        "days": day_items,
        "totals": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "est_cost_usd": _estimate_cost_usd(total_in, total_out),
        },
        "window_days": days,
        "input_usd_per_mtok": _INPUT_USD_PER_MTOK,
        "output_usd_per_mtok": _OUTPUT_USD_PER_MTOK,
    }


__all__ = ["get_llm_usage_summary"]
