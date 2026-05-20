"""Garmin Connect integration (SPEC §8.1).

Thin async wrapper over the synchronous `garminconnect` library. All blocking
calls are dispatched via `asyncio.to_thread`. OAuth tokens are persisted by
`garth` under `~/.garminconnect/` (handled by the library, not us).

Errors are surfaced as typed exceptions so callers can decide whether to retry
or notify the user (a single Discord DM on auth failure, per SPEC §8.1).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from lattice.config import settings

logger = logging.getLogger(__name__)

# garminconnect persists OAuth tokens here via `garth`.
TOKEN_STORE = Path.home() / ".garminconnect"


class GarminAuthError(RuntimeError):
    """Auth failed — user needs to re-login."""


class GarminUnavailable(RuntimeError):
    """Transient network / rate-limit / 5xx — retry later."""


class GarminClient:
    """Lazy-login wrapper. Reuses the cached token across calls.

    Thread-safe enough for our single-user case: a single asyncio lock guards
    login attempts, but post-login calls can run concurrently.
    """

    def __init__(self) -> None:
        self._client: Garmin | None = None
        self._login_lock = asyncio.Lock()

    async def _ensure_login(self) -> Garmin:
        if self._client is not None:
            return self._client
        async with self._login_lock:
            if self._client is not None:
                return self._client
            if not settings.garmin_email or not settings.garmin_password:
                raise GarminAuthError(
                    "GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env"
                )
            TOKEN_STORE.mkdir(parents=True, exist_ok=True)

            def _login() -> Garmin:
                client = Garmin(
                    email=settings.garmin_email,
                    password=settings.garmin_password,
                    is_cn=False,
                )
                # Try cached tokens first, fall back to password login.
                try:
                    client.login(str(TOKEN_STORE))
                except Exception:  # noqa: BLE001 — library raises various
                    client.login()
                    client.garth.dump(str(TOKEN_STORE))
                return client

            try:
                self._client = await asyncio.to_thread(_login)
            except GarminConnectAuthenticationError as exc:
                logger.error("garmin auth failed: %s", exc)
                raise GarminAuthError(str(exc)) from exc
            except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
                logger.warning("garmin transient error during login: %s", exc)
                raise GarminUnavailable(str(exc)) from exc
            logger.info("garmin login ok (tokens cached at %s)", TOKEN_STORE)
            return self._client

    async def _call(self, name: str, *args: Any) -> Any:
        """Invoke a method on the Garmin client in a worker thread."""
        client = await self._ensure_login()
        method = getattr(client, name)
        try:
            return await asyncio.to_thread(method, *args)
        except GarminConnectAuthenticationError as exc:
            # Token expired mid-session.
            self._client = None
            logger.error("garmin token expired during %s: %s", name, exc)
            raise GarminAuthError(str(exc)) from exc
        except (GarminConnectConnectionError, GarminConnectTooManyRequestsError) as exc:
            logger.warning("garmin transient error on %s: %s", name, exc)
            raise GarminUnavailable(str(exc)) from exc

    # --- typed-ish methods ---

    async def get_sleep(self, day: date) -> dict[str, Any]:
        return await self._call("get_sleep_data", day.isoformat())

    async def get_hrv(self, day: date) -> dict[str, Any] | None:
        return await self._call("get_hrv_data", day.isoformat())

    async def get_stress(self, day: date) -> dict[str, Any]:
        return await self._call("get_stress_data", day.isoformat())

    async def get_body_battery(self, day: date) -> list[dict[str, Any]]:
        return await self._call(
            "get_body_battery", day.isoformat(), day.isoformat()
        )

    async def get_heart_rates(self, day: date) -> dict[str, Any]:
        return await self._call("get_heart_rates", day.isoformat())

    async def get_steps(self, day: date) -> list[dict[str, Any]]:
        return await self._call("get_steps_data", day.isoformat())

    async def get_stats(self, day: date) -> dict[str, Any]:
        """Daily user summary: kcals, intensity minutes, floors, distance."""
        return await self._call("get_stats", day.isoformat())

    async def get_activities(self, start: date, end: date) -> list[dict[str, Any]]:
        return await self._call(
            "get_activities_by_date", start.isoformat(), end.isoformat()
        )

    async def get_training_status(self, day: date) -> dict[str, Any]:
        return await self._call("get_training_status", day.isoformat())

    async def get_respiration(self, day: date) -> dict[str, Any]:
        return await self._call("get_respiration_data", day.isoformat())

    async def get_spo2(self, day: date) -> dict[str, Any]:
        return await self._call("get_spo2_data", day.isoformat())


# Module-level singleton (single-user app; one Garmin session is enough).
_singleton: GarminClient | None = None


def get_client() -> GarminClient:
    global _singleton
    if _singleton is None:
        _singleton = GarminClient()
    return _singleton
