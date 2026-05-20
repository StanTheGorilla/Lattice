"""Pydantic schemas for the `metrics` table and its endpoints.

Endpoints covered (SPEC §5.3, §5.8):
  GET /metrics, GET /metrics/latest, GET /metrics/baseline,
  POST /sync/garmin.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    timestamp: str
    metric_name: str
    value: float
    unit: str | None = None
    source: str
    # Read from ORM attribute `extra_metadata`; serialize as `metadata` in JSON to match SPEC §4.2.
    extra_metadata: str | None = Field(default=None, serialization_alias="metadata")


class MetricListResponse(BaseModel):
    items: list[MetricOut]
    total: int


class MetricsLatestResponse(BaseModel):
    items: dict[str, MetricOut | None]


class BaselineResponse(BaseModel):
    name: str
    mean: float | None
    sd: float | None
    n: int
    window_days: int


class GarminSyncResult(BaseModel):
    metrics_written: int
    workouts_written: int = 0
    samples_written: int = 0
    stages_written: int = 0
    dates: list[str]
    errors: list[str] = Field(default_factory=list)
