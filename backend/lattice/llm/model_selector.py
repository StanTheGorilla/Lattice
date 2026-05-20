"""Per-intent model selection (SPEC §7.3).

Lightweight keyword-based classifier — no LLM. SPEC §7.3 maps intent classes
to DeepSeek model tiers. v1 ships two: chat (`deepseek-chat`) and reasoner
(`deepseek-reasoner`). Reasoner is reserved for messages that look like
scheduling / second-opinion / multi-step reasoning. Everything else uses the
default chat tier.

Override env vars: DEEPSEEK_MODEL_DEFAULT (chat) and DEEPSEEK_MODEL_REASONER.
"""

from __future__ import annotations

import re

from lattice.config import settings

_REASONING_PATTERNS = re.compile(
    r"\b("
    # scheduling-style intents
    r"plan|schedule|reschedule|optimal|best time|when should|when to|"
    # multi-step reasoning
    r"compare|trade(?:[- ]?off)?|why|because|"
    # second opinion
    r"second opinion|do you agree|disagree|are you sure"
    r")\b",
    re.IGNORECASE,
)


def needs_reasoner(user_message: str) -> bool:
    """True when the message looks like it benefits from chain-of-thought."""
    if not user_message:
        return False
    return bool(_REASONING_PATTERNS.search(user_message))


def pick_chat_model(user_message: str) -> str:
    """Return the DeepSeek model id to use for this turn."""
    if needs_reasoner(user_message):
        return settings.deepseek_model_reasoner
    return settings.deepseek_model_default


__all__ = ["needs_reasoner", "pick_chat_model"]
