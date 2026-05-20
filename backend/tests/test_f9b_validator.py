"""F9b safeguard validator tests."""

from __future__ import annotations

import pytest

from lattice.llm.f9b_validator import (
    NOTE_MISSING_STRUCTURE,
    enforce,
    has_required_structure,
    looks_like_second_opinion,
)


@pytest.mark.parametrize(
    "msg",
    [
        "second opinion: should I train hard today?",
        "Do you agree with the recommendation?",
        "what's your take on this?",
        "I disagree — should I rest instead?",
        "are you sure that's right?",
    ],
)
def test_detects_second_opinion(msg: str) -> None:
    assert looks_like_second_opinion(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "log a coffee",
        "what was my resting heart rate this morning",
        "give me my readiness",
    ],
)
def test_not_second_opinion(msg: str) -> None:
    assert looks_like_second_opinion(msg) is False


def test_has_required_structure_when_both_markers_present() -> None:
    reply = (
        "Algorithm recommends: easy session.\n"
        "Reasons: low readiness.\n\n"
        "My take: I agree — HRV is well below baseline."
    )
    assert has_required_structure(reply) is True


def test_missing_structure() -> None:
    assert has_required_structure("You should probably just rest.") is False


def test_enforce_prepends_when_second_opinion_lacks_structure() -> None:
    out = enforce("do you agree?", "Just rest today.")
    assert out.startswith(NOTE_MISSING_STRUCTURE)
    assert out.endswith("Just rest today.")


def test_enforce_passes_through_when_structure_present() -> None:
    reply = (
        "Algorithm recommends: rest.\n\n"
        "My take: makes sense to me."
    )
    out = enforce("second opinion?", reply)
    assert out == reply


def test_enforce_passes_through_when_not_second_opinion() -> None:
    out = enforce("log a coffee", "Logged a coffee.")
    assert out == "Logged a coffee."
