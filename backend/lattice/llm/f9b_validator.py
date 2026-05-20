"""F9b safeguard validator (SPEC §6 F9b).

When the user invokes a "second opinion" intent on Lattice's recommendation,
SPEC §6 F9b prescribes the reply must follow the structure:

  Algorithm recommends: <verbatim get_advice output>
  Reasons: <verbatim>

  My take: <model's view, grounded in retrieved data>

The system prompt instructs the model to do this; this validator is a
post-hoc safety net that detects when the model skipped the format and
appends a note so the user knows the second-opinion structure isn't being
followed for that reply.

We deliberately do NOT re-compute F9a here — without confident intent
classification, prepending an algorithm output could fabricate a
recommendation for a different intent than the one the user was second-
guessing. A short structural note is the safest fallback.
"""

from __future__ import annotations

import re

_SECOND_OPINION_PATTERNS = re.compile(
    r"\b("
    r"second opinion|"
    r"do you (?:agree|think)|"
    r"what(?:'s| is) your (?:take|view|opinion|read)|"
    r"your take|"
    r"i disagree|"
    r"are you sure|"
    r"is that (?:right|correct)|"
    r"second-guess"
    r")\b",
    re.IGNORECASE,
)

_ALGORITHM_MARKER = re.compile(r"\balgorithm recommends\b", re.IGNORECASE)
_MY_TAKE_MARKER = re.compile(r"\bmy (?:take|read|view)\b", re.IGNORECASE)

NOTE_MISSING_STRUCTURE = (
    "_(F9b note: second opinion was requested but the algorithm/take structure "
    "was not followed. Treat the reply as a single view, not as an algorithm "
    "comparison.)_\n\n"
)


def looks_like_second_opinion(user_message: str) -> bool:
    return bool(_SECOND_OPINION_PATTERNS.search(user_message))


def has_required_structure(reply: str) -> bool:
    return bool(_ALGORITHM_MARKER.search(reply) and _MY_TAKE_MARKER.search(reply))


def enforce(user_message: str, reply: str) -> str:
    """Return the reply unchanged, or prefixed with the structural note."""
    if not reply:
        return reply
    if not looks_like_second_opinion(user_message):
        return reply
    if has_required_structure(reply):
        return reply
    return NOTE_MISSING_STRUCTURE + reply


__all__ = [
    "NOTE_MISSING_STRUCTURE",
    "enforce",
    "has_required_structure",
    "looks_like_second_opinion",
]
