"""FastAPI entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from lattice.api import (
    alerts,
    auth,
    calendar,
    chat,
    entries,
    functions,
    habits,
    health,
    metrics,
    nutrition,
    planning,
    reports,
    research,
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

@app.get("/", response_class=PlainTextResponse, include_in_schema=False)
async def root() -> str:
    return (
        "LATTICE backend — API only.\n"
        "Open the UI at http://localhost:5173\n"
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
