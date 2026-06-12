"""Auth endpoints (SPEC §5.1)."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel

from lattice.auth import (
    SESSION_COOKIE_MAX_AGE,
    SESSION_COOKIE_NAME,
    mint_session_token,
    verify_session_token,
    web_is_open,
)
from lattice.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# In-process token bucket per remote IP — 10 attempts / minute is plenty for
# a single human, hostile enough for a script. Single-user app, no need for
# a Redis-backed limiter.
_LOGIN_RATE_LIMIT_MAX = 10
_LOGIN_RATE_LIMIT_WINDOW_S = 60.0
_login_attempts: dict[str, deque[float]] = {}


def _check_login_rate_limit(remote_ip: str) -> None:
    now = time.monotonic()
    bucket = _login_attempts.setdefault(remote_ip, deque())
    cutoff = now - _LOGIN_RATE_LIMIT_WINDOW_S
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _LOGIN_RATE_LIMIT_MAX:
        logger.warning("auth: rate-limit hit for %s", remote_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "rate_limited", "message": "too many login attempts"},
        )
    bucket.append(now)


class LoginRequest(BaseModel):
    password: str


class StatusResponse(BaseModel):
    authenticated: bool
    permissive: bool


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    payload: LoginRequest, request: Request, response: Response,
) -> dict[str, bool]:
    remote = request.client.host if request.client else "unknown"
    _check_login_rate_limit(remote)
    expected = settings.web_ui_password
    if not expected:
        # Dev-permissive: accept any password but still mint a cookie so the
        # frontend's auth gate doesn't loop.
        token = mint_session_token()
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            max_age=SESSION_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=False,  # local dev only
        )
        return {"ok": True, "permissive": True}
    if payload.password != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "bad_password", "message": "incorrect password"},
        )
    token = mint_session_token()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {"ok": True, "permissive": False}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


@router.get("/status", response_model=StatusResponse)
async def auth_status(
    lattice_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> StatusResponse:
    if web_is_open():
        return StatusResponse(authenticated=True, permissive=True)
    if lattice_session and verify_session_token(lattice_session):
        return StatusResponse(authenticated=True, permissive=False)
    return StatusResponse(authenticated=False, permissive=False)
