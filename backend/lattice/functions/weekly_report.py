"""F7 — Weekly Pattern Report orchestrator (SPEC §6).

Two-stage pipeline:
  Stage A (deterministic): `weekly_stats.compute_weekly_stats` produces a
    structured JSON snapshot of the ISO week.
  Stage B (LLM): DeepSeek receives Stage A + the locked weekly-report prompt
    (SPEC §7.5) and returns ≤200 words of prose. The LLM cannot introduce
    new metrics or correlations beyond Stage A — the system prompt forbids it,
    and Stage A is the only data surface the model sees in this call.

Persistence is keyed on `iso_week` (UPSERT) so manual re-runs always reflect
the latest pass. SPEC §11 IN list: "F7 via scheduled job (LLM-assisted weekly
report, constrained prompt)".

The Stage B model is `settings.deepseek_model_default` (decision 2I-2). SPEC §7.3
prescribed `deepseek-v4-pro` with thinking; we ship a simpler v1 using the same
model as chat. Override via env if desired.

LLM failure mode: if Stage B fails (DeepSeek down, key missing), the report is
still persisted with `model_used="deterministic-only"` and `summary_text=<a
short deterministic summary built from Stage A>`. The user always gets a row,
even on a bad day.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.functions.weekly_stats import WeeklyStats, compute_weekly_stats
from lattice.integrations.deepseek import (
    DeepSeekAuthError,
    DeepSeekAuthMissing,
    DeepSeekUnavailable,
    chat_completion,
)
from lattice.llm.budget import BudgetExceeded, check_budget, record_usage
from lattice.llm.prompts import WEEKLY_REPORT_PROMPT
from lattice.models import WeeklyReport

logger = logging.getLogger(__name__)

# SPEC §6 F7: token output capped at 1000 (≤200 word target).
MAX_OUTPUT_TOKENS = 1000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _deterministic_fallback(stats: WeeklyStats) -> str:
    """Build a terse summary entirely from Stage A. No LLM."""
    lines = [
        f"Week {stats.iso_week} ({stats.week_start} → {stats.week_end}).",
    ]
    avg_readiness = stats.averages.get("readiness")
    if avg_readiness is not None:
        lines.append(f"Avg readiness {avg_readiness}.")
    if stats.best_day:
        lines.append(
            f"Best day: {stats.best_day.date} (readiness {stats.best_day.readiness}; "
            f"{stats.best_day.reason}).",
        )
    if stats.worst_day:
        lines.append(
            f"Worst day: {stats.worst_day.date} (readiness {stats.worst_day.readiness}; "
            f"{stats.worst_day.reason}).",
        )
    if stats.correlations:
        c = stats.correlations[0]
        lines.append(f"Notable correlation: {c.label} r={c.r} (n={c.n}).")
    if stats.mean_shifts:
        m = stats.mean_shifts[0]
        lines.append(
            f"Mean shift: {m.metric} {m.direction} {abs(m.delta_sd)}σ vs trailing "
            f"({m.this_week_mean} vs {m.trailing_mean}).",
        )
    if stats.coverage_notes:
        lines.append("Coverage: " + "; ".join(stats.coverage_notes) + ".")
    lines.append("(LLM synthesis unavailable; deterministic summary.)")
    return " ".join(lines)


async def _generate_summary(
    session: AsyncSession, stats: WeeklyStats,
) -> tuple[str, str]:
    """Call DeepSeek for Stage B. Returns (summary_text, model_used).

    Falls back to a deterministic summary on any LLM error so the row always
    persists.
    """
    payload = {
        "role": "user",
        "content": (
            "Stage A statistics for this week:\n"
            f"```json\n{json.dumps(stats.to_json_dict(), indent=2)}\n```"
        ),
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": WEEKLY_REPORT_PROMPT},
        payload,
    ]
    model = settings.deepseek_model_default
    try:
        await check_budget(session)
        completion = await chat_completion(
            messages=messages, tools=None, model=model, temperature=0.4,
        )
        await record_usage(session, completion)
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            logger.warning("weekly report: LLM returned empty content; falling back")
            return _deterministic_fallback(stats), "deterministic-only"
        return text, model
    except (DeepSeekAuthMissing, DeepSeekAuthError, DeepSeekUnavailable, BudgetExceeded) as exc:
        logger.warning("weekly report: LLM unavailable (%s); falling back", exc)
        return _deterministic_fallback(stats), "deterministic-only"


async def generate_weekly_report(
    session: AsyncSession,
    *,
    target: date,
    tz: str | None = None,
) -> WeeklyReport:
    """Compute Stage A + Stage B for the ISO week containing `target`,
    UPSERT into `weekly_reports`, return the persisted row.
    """
    stats = await compute_weekly_stats(session, target=target, tz=tz)
    summary_text, model_used = await _generate_summary(session, stats)
    stats_json = json.dumps(stats.to_json_dict())
    now = _now_iso()

    insert_stmt = sqlite_insert(WeeklyReport.__table__).values(
        iso_week=stats.iso_week,
        generated_at=now,
        model_used=model_used,
        stats_json=stats_json,
        summary_text=summary_text,
    ).on_conflict_do_update(
        index_elements=["iso_week"],
        set_={
            "generated_at": now,
            "model_used": model_used,
            "stats_json": stats_json,
            "summary_text": summary_text,
        },
    )
    await session.execute(insert_stmt)
    await session.commit()
    # Identity map may hold a stale row from a prior generate() in the same
    # session; expire so the re-select reads the just-UPSERTed values.
    session.expire_all()

    fetched = (
        await session.execute(
            select(WeeklyReport).where(WeeklyReport.iso_week == stats.iso_week),
        )
    ).scalar_one()
    return fetched


async def get_weekly_report(
    session: AsyncSession, iso_week: str,
) -> WeeklyReport | None:
    stmt = select(WeeklyReport).where(WeeklyReport.iso_week == iso_week)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_weekly_report(session: AsyncSession) -> WeeklyReport | None:
    stmt = select(WeeklyReport).order_by(WeeklyReport.iso_week.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_weekly_report_weeks(session: AsyncSession) -> list[str]:
    """Return iso_weeks (newest first) for which a report exists."""
    stmt = select(WeeklyReport.iso_week).order_by(WeeklyReport.iso_week.desc())
    return [row for (row,) in (await session.execute(stmt)).all()]


__all__ = [
    "MAX_OUTPUT_TOKENS",
    "generate_weekly_report",
    "get_latest_weekly_report",
    "get_weekly_report",
    "list_weekly_report_weeks",
]
