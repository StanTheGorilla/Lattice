"""Tests for functions/nutrition.py (P2-2).

`chat_completion` is mocked — no live DeepSeek call (CLAUDE.md).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lattice.functions import nutrition
from lattice.functions.nutrition import estimate_nutrition
from lattice.integrations.deepseek import DeepSeekUnavailable


def _fake_resp(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


@pytest.mark.asyncio
async def test_estimate_parses_plain_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake(messages, temperature):  # type: ignore[no-untyped-def]
        return _fake_resp(
            '{"calories": 250, "protein_g": 30, "carbs_g": 0, "fat_g": 14, '
            '"fiber_g": 0, "sugar_g": 0, "estimated_grams": 150, '
            '"confidence": "high", "notes": null}'
        )

    monkeypatch.setattr(nutrition, "chat_completion", fake)
    est = await estimate_nutrition("chicken breast", 150)
    assert est is not None
    assert est.calories == 250.0
    assert est.protein_g == 30.0
    assert est.confidence == "high"
    assert est.notes is None


@pytest.mark.asyncio
async def test_estimate_strips_markdown_fence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake(messages, temperature):  # type: ignore[no-untyped-def]
        return _fake_resp(
            '```json\n{"calories": 100, "protein_g": 1, "carbs_g": 25, '
            '"fat_g": 0, "fiber_g": 4, "sugar_g": 19, "estimated_grams": 100, '
            '"confidence": "medium", "notes": "apple"}\n```'
        )

    monkeypatch.setattr(nutrition, "chat_completion", fake)
    est = await estimate_nutrition("apple")
    assert est is not None
    assert est.calories == 100.0
    assert est.confidence == "medium"
    assert est.notes == "apple"


@pytest.mark.asyncio
async def test_estimate_empty_description_returns_none(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    est = await estimate_nutrition("   ")
    assert est is None


@pytest.mark.asyncio
async def test_estimate_returns_none_on_malformed_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake(messages, temperature):  # type: ignore[no-untyped-def]
        return _fake_resp("not json at all")

    monkeypatch.setattr(nutrition, "chat_completion", fake)
    assert await estimate_nutrition("mystery stew") is None


@pytest.mark.asyncio
async def test_estimate_returns_none_when_deepseek_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake(messages, temperature):  # type: ignore[no-untyped-def]
        raise DeepSeekUnavailable("down")

    monkeypatch.setattr(nutrition, "chat_completion", fake)
    assert await estimate_nutrition("salad") is None
