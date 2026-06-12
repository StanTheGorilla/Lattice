"""Pydantic schemas for the `recommendations` keyed store (Phase A).

`SleepRecommendation` is a superset of `SleepWindowOutput` (the raw F4 shape)
plus provenance fields (`source`, `rationale`, `author`). Returning a superset
means the website Today page and the Discord brief — which already read the
`/functions/sleep_window` endpoint — converge on the stored value with no
client changes, while new surfaces can show the AI/formula badge + rationale.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RecommendationSource = Literal["ai", "formula"]


class SleepRecommendation(BaseModel):
    date: str
    bedtime: str  # ISO 8601 with TZ offset
    wake_time: str  # ISO 8601 with TZ offset
    target_duration_min: float
    flags: list[str] = Field(default_factory=list)
    inputs: dict[str, str | bool | int | float | None] = Field(default_factory=dict)
    source: RecommendationSource
    rationale: str | None = None
    author: str | None = None


__all__ = ["RecommendationSource", "SleepRecommendation"]
