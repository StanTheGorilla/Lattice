"""F9a — Intent-Based Advisor (SPEC §6).

Canonical recommendation surface for `/today` slash command and web UI.
No LLM inside this function — pure rule cascade per intent.

The router enforces 'paraphrase only' / 'second opinion' separation;
this module is the deterministic source it paraphrases (Section 7.5).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.readiness import compute_readiness
from lattice.functions.training_rec import compute_training_rec
from lattice.functions.work_windows import compute_work_windows
from lattice.schemas.functions import (
    AdvisorIntent,
    AdvisorOutput,
    WorkWindow,
)

MIN_WINDOW_MINUTES = 60
LEARN_REST_THRESHOLD = 35
CREATIVE_REST_THRESHOLD = 25
STRONG_FOCUS_THRESHOLD = 70
MODERATE_FOCUS_THRESHOLD = 50


def _top_window(windows: list[WorkWindow]) -> WorkWindow | None:
    return windows[0] if windows else None


async def _learn_or_creative(
    session: AsyncSession,
    *,
    target: date,
    tz: str,
    rest_threshold: int,
) -> AdvisorOutput:
    readiness = await compute_readiness(session, target=target, tz=tz)
    intent_label: AdvisorIntent = (
        "creative" if rest_threshold == CREATIVE_REST_THRESHOLD else "learn"
    )

    if readiness.score < rest_threshold:
        return AdvisorOutput(
            intent=intent_label,
            recommendation="rest_recommended",
            confidence=0.9,
            reasons=[
                f"readiness depleted: {readiness.score}",
                f"cognitive performance impaired below ~{rest_threshold}",
            ],
        )

    windows = await compute_work_windows(
        session,
        target=target,
        tz=tz,
        min_minutes=MIN_WINDOW_MINUTES,
        readiness_score=readiness.score,
    )
    top = _top_window(windows.windows)
    if top is None:
        return AdvisorOutput(
            intent=intent_label,
            recommendation="no_window_available",
            confidence=1.0,
            reasons=[f"calendar fragmented, no {MIN_WINDOW_MINUTES}+ min gap today"],
        )
    if top.predicted_focus >= STRONG_FOCUS_THRESHOLD:
        rec = "window_strong"
        confidence = 0.85
        reasons = top.rationale
    elif top.predicted_focus >= MODERATE_FOCUS_THRESHOLD:
        rec = "window_moderate"
        confidence = 0.6
        reasons = [*top.rationale, "not optimal but viable"]
    else:
        rec = "window_weak"
        confidence = 0.4
        reasons = ["best available window; expect reduced output"]
    return AdvisorOutput(
        intent=intent_label,
        recommendation=rec,
        confidence=confidence,
        window=top,
        reasons=reasons,
        alternatives=windows.windows[1:],
    )


async def _train(
    session: AsyncSession, *, target: date, tz: str,
) -> AdvisorOutput:
    readiness = await compute_readiness(session, target=target, tz=tz)
    rec = await compute_training_rec(
        session, target=target, tz=tz, readiness_score=readiness.score,
    )
    if rec.recommendation == "rest":
        return AdvisorOutput(
            intent="train",
            recommendation="rest_day",
            confidence=rec.confidence,
            reasons=rec.rationale,
        )
    windows = await compute_work_windows(
        session,
        target=target,
        tz=tz,
        min_minutes=MIN_WINDOW_MINUTES,
        readiness_score=readiness.score,
    )
    if windows.windows:
        return AdvisorOutput(
            intent="train",
            recommendation=f"train_{rec.recommendation}",
            confidence=0.8,
            window=windows.windows[0],
            reasons=rec.rationale,
        )
    return AdvisorOutput(
        intent="train",
        recommendation="train_short_or_skip",
        confidence=0.5,
        reasons=[
            "only short gaps available",
            "consider 20-min session or postpone",
            *rec.rationale,
        ],
    )


async def _rest(
    session: AsyncSession, *, target: date, tz: str,
) -> AdvisorOutput:
    """Returns the stored sleep recommendation (AI decision if present, else F4
    seed) verbatim, with flags + rationale as reasons."""
    from lattice.functions.recommendation_store import get_active_sleep_recommendation

    sleep = await get_active_sleep_recommendation(session, target=target, tz=tz)
    reasons = [
        f"bedtime {sleep.bedtime} → wake {sleep.wake_time}",
        f"target duration {sleep.target_duration_min:.0f} min",
        *sleep.flags,
    ]
    if sleep.source == "ai" and sleep.rationale:
        reasons.append(f"AI: {sleep.rationale}")
    return AdvisorOutput(
        intent="rest",
        recommendation="sleep_window",
        confidence=0.9,
        reasons=reasons,
    )


async def _meeting(
    session: AsyncSession, *, target: date, tz: str,
) -> AdvisorOutput:
    """Suggest first gap ≥30min OUTSIDE the top 2 focus windows."""
    readiness = await compute_readiness(session, target=target, tz=tz)
    windows = await compute_work_windows(
        session, target=target, tz=tz, min_minutes=30, readiness_score=readiness.score,
    )
    if not windows.windows:
        return AdvisorOutput(
            intent="meeting",
            recommendation="no_slot",
            confidence=0.9,
            reasons=["no 30-min gap available today"],
        )
    top_focus_ids = {(w.start, w.end) for w in windows.windows[:2]}
    candidates = [w for w in windows.windows if (w.start, w.end) not in top_focus_ids]
    suggested = candidates[0] if candidates else windows.windows[0]
    reasons = [
        "preserving top 2 focus windows for deep work",
        f"suggested slot {suggested.start}–{suggested.end}",
    ]
    # Flag if it falls in a low-focus hour (predicted_focus < moderate).
    if suggested.predicted_focus < MODERATE_FOCUS_THRESHOLD:
        reasons.append(
            f"warning: low predicted focus ({suggested.predicted_focus})",
        )
    return AdvisorOutput(
        intent="meeting",
        recommendation="meeting_slot",
        confidence=0.7,
        window=suggested,
        reasons=reasons,
    )


async def _physical_task(
    session: AsyncSession, *, target: date, tz: str,
) -> AdvisorOutput:
    """Pick windows with LOW predicted_focus — energy dip is fine."""
    readiness = await compute_readiness(session, target=target, tz=tz)
    windows = await compute_work_windows(
        session, target=target, tz=tz, min_minutes=30, readiness_score=readiness.score,
    )
    if not windows.windows:
        return AdvisorOutput(
            intent="physical_task",
            recommendation="no_window",
            confidence=0.9,
            reasons=["no 30-min gap available today"],
        )
    ranked = sorted(windows.windows, key=lambda w: w.predicted_focus)
    suggested = ranked[0]
    return AdvisorOutput(
        intent="physical_task",
        recommendation="physical_slot",
        confidence=0.7,
        window=suggested,
        reasons=[
            "low-focus window is fine for chores/errands",
            f"predicted focus {suggested.predicted_focus} (lower = preferred)",
        ],
        alternatives=ranked[1:],
    )


async def compute_advisor(
    session: AsyncSession,
    *,
    intent: AdvisorIntent,
    target: date,
    tz: str,
) -> AdvisorOutput:
    """Dispatch to the per-intent rule table."""
    if intent == "learn":
        return await _learn_or_creative(
            session, target=target, tz=tz, rest_threshold=LEARN_REST_THRESHOLD,
        )
    if intent == "creative":
        return await _learn_or_creative(
            session, target=target, tz=tz, rest_threshold=CREATIVE_REST_THRESHOLD,
        )
    if intent == "train":
        return await _train(session, target=target, tz=tz)
    if intent == "rest":
        return await _rest(session, target=target, tz=tz)
    if intent == "meeting":
        return await _meeting(session, target=target, tz=tz)
    if intent == "physical_task":
        return await _physical_task(session, target=target, tz=tz)
    raise ValueError(f"unsupported intent: {intent}")


__all__ = ["compute_advisor"]
