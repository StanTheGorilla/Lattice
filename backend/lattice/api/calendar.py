"""Calendar endpoints (SPEC §5.4).

`:id` path param is the Google event id (the identifier we store in
`calendar_cache.google_event_id`). Writes round-trip Google and write-through
the cache so subsequent reads see the change without waiting for the TTL.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.auth import require_auth
from lattice.config import settings
from lattice.db import get_session
from lattice.integrations.google_calendar import (
    GoogleAuthError,
    GoogleAuthMissing,
    GoogleUnavailable,
)
from lattice.schemas.calendar import (
    BusyInterval,
    CalendarEvent,
    CalendarEventCreate,
    CalendarEventPatch,
    CalendarSyncResult,
)
from lattice.sync.calendar_sync import (
    cached_events_or_refresh,
    create_event_remote,
    delete_event_remote,
    free_busy,
    patch_event_remote,
    row_to_event_body,
    sync_window,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/calendar", tags=["calendar"], dependencies=[Depends(require_auth)],
)


def _default_window() -> tuple[str, str]:
    now = datetime.now(UTC)
    return now.isoformat(timespec="seconds"), (now + timedelta(days=14)).isoformat(
        timespec="seconds",
    )


def _handle_google_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, GoogleAuthMissing):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "google_credentials_missing",
                "message": "Google Cloud OAuth client config missing — see README §Google Calendar setup",
                "details": str(exc),
            },
        )
    if isinstance(exc, GoogleAuthError):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "google_auth_failed",
                "message": "Google OAuth token rejected — delete cached token and retry",
                "details": str(exc),
            },
        )
    if isinstance(exc, GoogleUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "google_unavailable",
                "message": "Google Calendar transient error",
                "details": str(exc),
            },
        )
    raise exc  # let FastAPI return 500


@router.get("/events", response_model=list[CalendarEvent])
async def list_events(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> list[CalendarEvent]:
    try:
        rows = await cached_events_or_refresh(session, from_, to)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc
    return [CalendarEvent.model_validate(r) for r in rows]


@router.get("/freebusy", response_model=list[BusyInterval])
async def get_freebusy(
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> list[BusyInterval]:
    try:
        return await free_busy(session, from_, to)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc


@router.post("/events", response_model=CalendarEvent, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: CalendarEventCreate,
    session: AsyncSession = Depends(get_session),
) -> CalendarEvent:
    body = row_to_event_body(
        title=payload.title,
        start=payload.start,
        end=payload.end,
        description=payload.description,
        location=payload.location,
        is_all_day=payload.is_all_day,
        timezone_name=settings.timezone,
    )
    try:
        row = await create_event_remote(session, body)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc
    return CalendarEvent.model_validate(row)


@router.patch("/events/{event_id}", response_model=CalendarEvent)
async def patch_event(
    event_id: str,
    payload: CalendarEventPatch,
    session: AsyncSession = Depends(get_session),
) -> CalendarEvent:
    body: dict[str, object] = {}
    if payload.title is not None:
        body["summary"] = payload.title
    if payload.description is not None:
        body["description"] = payload.description
    if payload.location is not None:
        body["location"] = payload.location

    is_all_day = payload.is_all_day
    if payload.start is not None or payload.end is not None or is_all_day is not None:
        # Need both start and end to be self-consistent when crossing the
        # timed/all-day boundary. Require the client to send both if they're
        # changing one of them.
        if (payload.start is None) ^ (payload.end is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "incomplete_time_change",
                    "message": "start and end must be patched together",
                },
            )
        if payload.start is not None and payload.end is not None:
            all_day = bool(is_all_day) if is_all_day is not None else False
            if all_day:
                body["start"] = {"date": payload.start}
                body["end"] = {"date": payload.end}
            else:
                body["start"] = {"dateTime": payload.start, "timeZone": settings.timezone}
                body["end"] = {"dateTime": payload.end, "timeZone": settings.timezone}

    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "empty_patch", "message": "no fields to update"},
        )

    try:
        row = await patch_event_remote(session, event_id, body)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc
    return CalendarEvent.model_validate(row)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    try:
        await delete_event_remote(session, event_id)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc


@router.post("/sync", response_model=CalendarSyncResult)
async def sync_calendar(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> CalendarSyncResult:
    if from_ is None or to is None:
        default_from, default_to = _default_window()
        from_ = from_ or default_from
        to = to or default_to
    try:
        written = await sync_window(session, from_, to)
    except (GoogleAuthMissing, GoogleAuthError, GoogleUnavailable) as exc:
        raise _handle_google_errors(exc) from exc
    return CalendarSyncResult(refreshed=written, window_from=from_, window_to=to)
