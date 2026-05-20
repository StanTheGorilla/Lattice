"""Research paper endpoints — list and read papers saved by the research agent."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from lattice.auth import require_auth
from lattice.integrations.research import list_papers, read_paper

router = APIRouter(
    prefix="/research",
    tags=["research"],
    dependencies=[Depends(require_auth)],
)


@router.get("/papers")
async def list_research_papers(
    topic: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List all saved research papers, newest-first."""
    return list_papers(topic=topic)


@router.get("/papers/{filename}")
async def get_research_paper(filename: str) -> dict[str, Any]:
    """Read a research paper by filename. Returns raw markdown content."""
    try:
        content = read_paper(filename)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "filename": filename},
        )
    return {"filename": filename, "content": content}


__all__ = ["router"]
