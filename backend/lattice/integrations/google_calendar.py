"""Google Calendar integration (SPEC §8.2).

Thin async wrapper over the synchronous `google-api-python-client`. All blocking
calls are dispatched via `asyncio.to_thread`.

Auth is OAuth 2.0 "installed app" flow:
  - Client ID and secret are read from GOOGLE_OAUTH_CLIENT_ID /
    GOOGLE_OAUTH_CLIENT_SECRET env vars (set in .env). A legacy
    credentials.json file in this directory is used as a fallback.
  - First call without a cached token opens a browser for the consent screen.
  - The resulting token is cached at %USERPROFILE%/.lattice/google_token.json.

Errors:
  - `GoogleAuthMissing`  — client ID/secret not configured anywhere.
  - `GoogleAuthError`    — token rejected / refresh failed.
  - `GoogleUnavailable`  — transient (network, 5xx). Retry later.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# SPEC §8.2: credentials.json in backend/lattice/integrations/ (gitignored)
CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
TOKEN_DIR = Path.home() / ".lattice"
TOKEN_PATH = TOKEN_DIR / "google_token.json"


class GoogleAuthMissing(RuntimeError):
    """credentials.json is missing — user must complete Google Cloud setup."""


class GoogleAuthError(RuntimeError):
    """OAuth token invalid or refresh failed — re-run consent."""


class GoogleUnavailable(RuntimeError):
    """Transient Google API error — retry later."""


class GoogleCalendarClient:
    """Lazy-auth wrapper around the Calendar v3 service.

    Single-user app: one resource is shared across calls; an asyncio lock
    guards the auth bootstrap so the browser only opens once.
    """

    def __init__(self) -> None:
        self._service: Any = None
        self._auth_lock = asyncio.Lock()

    async def _ensure_service(self) -> Any:
        if self._service is not None:
            return self._service
        async with self._auth_lock:
            if self._service is not None:
                return self._service
            creds = await asyncio.to_thread(self._load_credentials)
            # `build` does a synchronous discovery fetch on first call.
            self._service = await asyncio.to_thread(
                build, "calendar", "v3", credentials=creds, cache_discovery=False,
            )
            logger.info("google calendar service ready (token at %s)", TOKEN_PATH)
            return self._service

    @staticmethod
    def _load_credentials() -> Credentials:
        """Load cached credentials or run the OAuth consent flow."""
        creds: Credentials | None = None
        if TOKEN_PATH.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning("token cache unreadable, will re-auth: %s", exc)
                creds = None

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_token(creds)
                return creds
            except RefreshError as exc:
                logger.error("token refresh failed: %s", exc)
                raise GoogleAuthError(
                    "Cached Google OAuth token rejected. Delete "
                    f"{TOKEN_PATH} and retry to trigger a new consent flow."
                ) from exc

        # No cached creds: run the consent flow.
        from lattice.config import settings

        if settings.google_oauth_client_id and settings.google_oauth_client_secret:
            client_config = {
                "installed": {
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        elif CREDENTIALS_PATH.exists():
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES,
            )
        else:
            raise GoogleAuthMissing(
                "Google OAuth credentials not configured. "
                "Set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in .env"
            )
        # port=0 → ephemeral; opens the user's default browser.
        creds = flow.run_local_server(port=0)
        _save_token(creds)
        return creds

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except HttpError as exc:
            status_code = exc.resp.status if exc.resp is not None else 0
            if status_code in (401, 403):
                self._service = None
                raise GoogleAuthError(str(exc)) from exc
            if status_code >= 500 or status_code == 429:
                raise GoogleUnavailable(str(exc)) from exc
            # 4xx other than auth — caller logic bug or bad input; re-raise.
            raise

    # ------------------------------------------------------------------ #
    # API surface
    # ------------------------------------------------------------------ #

    async def list_events(
        self, time_min: str, time_max: str, calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """List events in [time_min, time_max] inclusive. RFC3339 strings."""
        service = await self._ensure_service()

        def _go() -> list[dict[str, Any]]:
            items: list[dict[str, Any]] = []
            page_token: str | None = None
            while True:
                resp = (
                    service.events()
                    .list(
                        calendarId=calendar_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=250,
                        pageToken=page_token,
                    )
                    .execute()
                )
                items.extend(resp.get("items", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    return items

        return await self._call(_go)

    async def create_event(
        self, body: dict[str, Any], calendar_id: str = "primary",
    ) -> dict[str, Any]:
        service = await self._ensure_service()
        return await self._call(
            lambda: service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute(),
        )

    async def patch_event(
        self, event_id: str, body: dict[str, Any], calendar_id: str = "primary",
    ) -> dict[str, Any]:
        service = await self._ensure_service()
        return await self._call(
            lambda: service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=body)
            .execute(),
        )

    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> None:
        service = await self._ensure_service()
        await self._call(
            lambda: service.events()
            .delete(calendarId=calendar_id, eventId=event_id)
            .execute(),
        )


def _save_token(creds: Credentials) -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")


_singleton: GoogleCalendarClient | None = None


def get_client() -> GoogleCalendarClient:
    global _singleton
    if _singleton is None:
        _singleton = GoogleCalendarClient()
    return _singleton
