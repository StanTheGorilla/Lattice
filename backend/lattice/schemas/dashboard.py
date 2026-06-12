"""Dashboard card schemas (Phase 2L-c).

A card stores a *recipe* (data_source spec), not a snapshot. On every GET
the API resolves the recipe against current metric data, so the chart on
the dashboard always reflects the latest values.

data_source shapes:

  line/bar:
    {
      "days": 14,
      "series": [
        {"name": "Sleep (min)", "metric": "sleep_duration_min", "color": "#5dd0c8"},
        {"name": "Target",       "value": 450,                  "color": "#888"}
      ]
    }

  table:
    {
      "days": 7,
      "metric_columns": ["sleep_duration_min", "sleep_score"]
    }
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ChartType = Literal["line", "bar", "table"]


class SeriesSpec(BaseModel):
    """One series in a line/bar chart.

    Exactly one of `metric` or `value` should be set:
      - `metric` → fetch the last N daily values for that metric
      - `value`  → render a constant horizontal reference line
    """
    name: str
    metric: str | None = None
    value: float | None = None
    color: str | None = None


class DataSourceLineBar(BaseModel):
    days: int = Field(default=14, ge=1, le=365)
    series: list[SeriesSpec]


class DataSourceTable(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    metric_columns: list[str]


# Resolved (rendered) shapes — what the frontend consumes.

class ResolvedLineBar(BaseModel):
    chart_type: Literal["line", "bar"]
    labels: list[str]
    series: list[dict[str, Any]]


class ResolvedTable(BaseModel):
    chart_type: Literal["table"]
    columns: list[str]
    rows: list[list[Any]]


class DashboardCardOut(BaseModel):
    id: int
    title: str
    chart_type: ChartType
    position: int
    created_at: str
    data_source: dict[str, Any]
    resolved: ResolvedLineBar | ResolvedTable


class DashboardCardListResponse(BaseModel):
    items: list[DashboardCardOut]


class CardMoveRequest(BaseModel):
    direction: Literal["up", "down"]


__all__ = [
    "CardMoveRequest",
    "ChartType",
    "DashboardCardListResponse",
    "DashboardCardOut",
    "DataSourceLineBar",
    "DataSourceTable",
    "ResolvedLineBar",
    "ResolvedTable",
    "SeriesSpec",
]
