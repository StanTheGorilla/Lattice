"""FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from lattice.api import (
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


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
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
app.include_router(algorithms.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(routines.router, prefix="/api")


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
