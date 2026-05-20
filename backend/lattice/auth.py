"""Auth dependencies + session cookie helpers.

Accepts either:
  - `X-Bot-Token` header against `BOT_SHARED_SECRET` (bot ↔ backend)
  - `lattice_session` cookie signed via itsdangerous (web UI)

Permissive in dev when both `BOT_SHARED_SECRET` and `WEB_UI_PASSWORD` are
unset — the backend binds to 127.0.0.1 only (SPEC §10), so this is
acceptable for single-user local use.
"""

from __future__ import annotations

from fastapi import Cookie, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from lattice.config import settings

SESSION_COOKIE_NAME = "lattice_session"
SESSION_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days per SPEC §10
SESSION_SALT = "lattice-web-session"


def _serializer() -> URLSafeTimedSerializer:
    # `web_ui_password` doubles as the signing key — re-using the secret the
    # user already configured avoids introducing a separate SECRET_KEY env var.
    secret = settings.web_ui_password or "dev-permissive-key"
    return URLSafeTimedSerializer(secret, salt=SESSION_SALT)


def mint_session_token() -> str:
    """Return a signed token to be set as the `lattice_session` cookie."""
    return _serializer().dumps({"ok": True})


def verify_session_token(token: str) -> bool:
    try:
        _serializer().loads(token, max_age=SESSION_COOKIE_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False


def web_is_open() -> bool:
    """Web requests pass without a cookie when no password is configured.

    Bot auth is orthogonal — setting BOT_SHARED_SECRET locks bot endpoints
    via X-Bot-Token but does not lock the web. To lock the web, set
    WEB_UI_PASSWORD. Backend binds 127.0.0.1 (SPEC §10) so an open web is
    acceptable in single-user dev.
    """
    return not settings.web_ui_password


async def require_auth(
    x_bot_token: str | None = Header(default=None, alias="X-Bot-Token"),
    lattice_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> None:
    """Allow if any of: bot-token matches, web is open, valid session cookie."""
    if settings.bot_shared_secret and x_bot_token == settings.bot_shared_secret:
        return
    if web_is_open():
        return
    if lattice_session and verify_session_token(lattice_session):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": "unauthorized", "message": "authentication required"},
    )


__all__ = [
    "SESSION_COOKIE_MAX_AGE",
    "SESSION_COOKIE_NAME",
    "mint_session_token",
    "require_auth",
    "verify_session_token",
    "web_is_open",
]
