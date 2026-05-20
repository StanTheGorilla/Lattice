"""Manual sync triggers (SPEC §5.8) + last-sync status pill + SSE stream."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.integrations.garmin import GarminAuthError, GarminUnavailable, get_client
from lattice.models import CalendarCache, Metric
from lattice.schemas.metrics import GarminSyncResult
from lattice.sync.garmin_sync import sync_date, sync_recent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(require_auth)])

# Max-days cap matches the SSE endpoint: covers 1 year + slack for historical
# backfill. The non-stream endpoint is the same path the bot uses.
MAX_SYNC_DAYS = 400


class SyncStatus(BaseModel):
    garmin_last_metric_at: str | None
    calendar_last_fetched_at: str | None


@router.get("/status", response_model=SyncStatus)
async def sync_status(
    session: AsyncSession = Depends(get_session),
) -> SyncStatus:
    """Last-known sync activity. Derived, not stored — just max(timestamp)."""
    garmin = (
        await session.execute(
            select(func.max(Metric.timestamp)).where(Metric.source == "garmin"),
        )
    ).scalar_one_or_none()
    calendar = (
        await session.execute(select(func.max(CalendarCache.fetched_at)))
    ).scalar_one_or_none()
    return SyncStatus(garmin_last_metric_at=garmin, calendar_last_fetched_at=calendar)


@router.post("/garmin", response_model=GarminSyncResult)
async def sync_garmin(
    days: int = 1,
    session: AsyncSession = Depends(get_session),
) -> GarminSyncResult:
    if days < 1 or days > MAX_SYNC_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_range",
                "message": f"days must be 1..{MAX_SYNC_DAYS}",
            },
        )
    try:
        report = await sync_recent(session, days=days)
    except GarminAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "garmin_auth_failed",
                "message": "Garmin login failed — re-check GARMIN_EMAIL/GARMIN_PASSWORD",
                "details": str(exc),
            },
        ) from exc
    except GarminUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "garmin_unavailable",
                "message": "Garmin transient error",
                "details": str(exc),
            },
        ) from exc
    return GarminSyncResult(
        metrics_written=report.rows_written,
        workouts_written=report.workouts_written,
        samples_written=report.samples_written,
        stages_written=report.stages_written,
        dates=report.dates,
        errors=report.errors,
    )


@router.post("/garmin/stream")
async def sync_garmin_stream(
    days: int = 1,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """SSE stream: emits one progress event per day, then a final `done`.

    Each event is `data: <json>\\n\\n` where the payload is either:
      - `{type: "progress", day, done, total, metrics_written, workouts_written, errors[]}`
      - `{type: "done", metrics_total, workouts_total, total}`
      - `{type: "error", code, message}` — fatal (auth failure); client should stop.
    """
    if days < 1 or days > MAX_SYNC_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_range",
                "message": f"days must be 1..{MAX_SYNC_DAYS}",
            },
        )

    async def gen():  # type: ignore[no-untyped-def]
        tz = ZoneInfo(settings.timezone)
        today = datetime.now(tz).date()
        start_day = today - timedelta(days=days - 1)
        client = get_client()
        total = days
        done = 0
        metrics_total = 0
        workouts_total = 0
        samples_total = 0
        stages_total = 0
        cur = start_day
        while cur <= today:
            try:
                report = await sync_date(session, cur, client)
                metrics_total += report.rows_written
                workouts_total += report.workouts_written
                samples_total += report.samples_written
                stages_total += report.stages_written
                payload = {
                    "type": "progress",
                    "day": cur.isoformat(),
                    "done": done + 1,
                    "total": total,
                    "metrics_written": report.rows_written,
                    "workouts_written": report.workouts_written,
                    "samples_written": report.samples_written,
                    "stages_written": report.stages_written,
                    "errors": report.errors,
                }
            except GarminAuthError as exc:
                yield (
                    "data: "
                    + json.dumps({
                        "type": "error",
                        "code": "garmin_auth_failed",
                        "message": str(exc),
                    })
                    + "\n\n"
                )
                return
            except Exception as exc:  # noqa: BLE001 — surface as per-day error
                logger.warning("sync stream day %s failed: %s", cur, exc)
                payload = {
                    "type": "progress",
                    "day": cur.isoformat(),
                    "done": done + 1,
                    "total": total,
                    "metrics_written": 0,
                    "workouts_written": 0,
                    "samples_written": 0,
                    "stages_written": 0,
                    "errors": [str(exc)],
                }
            done += 1
            yield "data: " + json.dumps(payload) + "\n\n"
            cur += timedelta(days=1)
        yield (
            "data: "
            + json.dumps({
                "type": "done",
                "metrics_total": metrics_total,
                "workouts_total": workouts_total,
                "samples_total": samples_total,
                "stages_total": stages_total,
                "total": total,
            })
            + "\n\n"
        )

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
