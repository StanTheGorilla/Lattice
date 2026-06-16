"""FastAPI entry point."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from lattice.api import (
    ai_journal,
    alerts,
    algorithms,
    auth,
    calendar,
    chat,
    dashboard,
    entries,
    functions,
    habits,
    health,
    memory,
    metrics,
    nutrition,
    observability,
    pending_actions,
    planning,
    reports,
    research,
    routines,
    sync,
)
from lattice.config import configure_logging, settings
from lattice.sync import scheduler

configure_logging()
logger = logging.getLogger(__name__)


_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _detected_bind_host() -> str | None:
    """Best-effort sniff of the host uvicorn is binding to.

    Looks at `--host <value>` / `--host=<value>` in argv first (the way the
    systemd unit invokes uvicorn), then `UVICORN_HOST`. Returns None when
    nothing is found, in which case we assume the safe localhost default.
    """
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    return os.environ.get("UVICORN_HOST")


def _enforce_fail_closed_auth() -> None:
    """Refuse to start when the API is LAN-exposed without any auth secret.

    The original SPEC assumed a 127.0.0.1 bind; the Pi's systemd unit now
    binds 0.0.0.0:8000. `require_auth` is permissive when no password is
    configured, so an unset `WEB_UI_PASSWORD` + non-loopback bind would
    leave every endpoint reachable from the LAN. Fail closed instead.
    """
    host = _detected_bind_host()
    if host is None or host in _LOOPBACK_HOSTS:
        return
    if settings.web_ui_password or settings.bot_shared_secret:
        return
    raise RuntimeError(
        f"refusing to start: host '{host}' is non-loopback but neither "
        "WEB_UI_PASSWORD nor BOT_SHARED_SECRET is set. Set one of these "
        "in .env, or bind to 127.0.0.1.",
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    _enforce_fail_closed_auth()
    logger.info(
        "lattice backend starting — tz=%s scheduler=%s",
        settings.timezone,
        "disabled" if settings.lattice_disable_scheduler else "enabled",
    )
    scheduler.start()
    await scheduler.load_routines()
    yield
    scheduler.shutdown()
    logger.info("lattice backend stopping")


app = FastAPI(
    title="Lattice",
    description="Personal optimization system — backend API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", include_in_schema=False)
async def root() -> Response:
    index = settings.frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return PlainTextResponse(
        "LATTICE backend — API only (no frontend build found).\n"
        "Run `npm run build` in frontend/, or open the dev UI at http://localhost:5173\n"
        "Health: /api/health · Docs: /docs\n"
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    # No favicon graphic by design (CLAUDE.md: wordmark text only).
    # 204 silences the browser's auto-request without serving a graphic.
    return Response(status_code=204)


app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")
app.include_router(entries.router, prefix="/api")
app.include_router(habits.router, prefix="/api")
app.include_router(functions.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(planning.router, prefix="/api")
app.include_router(nutrition.router, prefix="/api")
app.include_router(research.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(memory.router, prefix="/api")
app.include_router(pending_actions.router, prefix="/api")
app.include_router(ai_journal.router, prefix="/api")
app.include_router(algorithms.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(routines.router, prefix="/api")
app.include_router(observability.router, prefix="/api")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str) -> Response:
    """Serve static build files; fall back to index.html for client-side routes.

    Registered after all /api routers and FastAPI's docs, so those take precedence.
    """
    dist = settings.frontend_dist.resolve()
    candidate = (dist / full_path).resolve()
    if full_path and candidate.is_file() and candidate.is_relative_to(dist):
        return FileResponse(candidate)
    index = settings.frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return PlainTextResponse("Not found", status_code=404)
