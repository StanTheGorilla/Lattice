"""Pydantic schemas for the weekly report endpoints (SPEC §5.7)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from lattice.models import WeeklyReport as WeeklyReportRow


class DailyAggregateOut(BaseModel):
    date: str
    readiness: int | None
    sleep_score: float | None
    sleep_duration_min: float | None
    hrv_overnight_avg: float | None
    resting_hr: float | None
    stress_avg: float | None


class BestWorstDayOut(BaseModel):
    date: str
    readiness: int
    reason: str


class HabitWeekStatOut(BaseModel):
    habit_id: int
    name: str
    target_per_week: int
    completed_this_week: int
    week_completion_pct: float
    current_streak_days: int


class CorrelationOut(BaseModel):
    label: str
    r: float
    n: int
    direction: str


class MeanShiftOut(BaseModel):
    metric: str
    this_week_mean: float
    trailing_mean: float
    trailing_sd: float
    delta_sd: float
    direction: str


class WeeklyStatsOut(BaseModel):
    iso_week: str
    week_start: str
    week_end: str
    daily: list[DailyAggregateOut]
    averages: dict[str, float | None]
    best_day: BestWorstDayOut | None
    worst_day: BestWorstDayOut | None
    habits: list[HabitWeekStatOut]
    correlations: list[CorrelationOut]
    mean_shifts: list[MeanShiftOut]
    coverage_notes: list[str]


class WeeklyReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    iso_week: str
    generated_at: str
    model_used: str
    stats: WeeklyStatsOut
    summary_text: str

    @classmethod
    def from_row(cls, row: WeeklyReportRow) -> WeeklyReportOut:
        try:
            stats_dict: Any = json.loads(row.stats_json)
        except json.JSONDecodeError:
            stats_dict = {
                "iso_week": row.iso_week,
                "week_start": "",
                "week_end": "",
                "daily": [],
                "averages": {},
                "best_day": None,
                "worst_day": None,
                "habits": [],
                "correlations": [],
                "mean_shifts": [],
                "coverage_notes": ["stats_json malformed"],
            }
        return cls(
            id=row.id,
            iso_week=row.iso_week,
            generated_at=row.generated_at,
            model_used=row.model_used,
            stats=WeeklyStatsOut.model_validate(stats_dict),
            summary_text=row.summary_text,
        )


__all__ = [
    "BestWorstDayOut",
    "CorrelationOut",
    "DailyAggregateOut",
    "HabitWeekStatOut",
    "MeanShiftOut",
    "WeeklyReportOut",
    "WeeklyStatsOut",
]
