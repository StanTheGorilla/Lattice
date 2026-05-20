"""Tavily Search API client for the research agent."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyAuthMissing(Exception):
    """TAVILY_API_KEY not set."""


class TavilyAuthError(Exception):
    """401 — invalid key."""


class TavilyUnavailable(Exception):
    """Service error or timeout."""


async def tavily_search(
    query: str,
    *,
    api_key: str,
    max_results: int = 5,
    search_depth: str = "advanced",
) -> dict[str, Any]:
    """Call Tavily /search. Returns raw JSON with 'results' and optional 'answer'."""
    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": True,
        "include_raw_content": False,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(TAVILY_SEARCH_URL, json=payload)
        except httpx.TimeoutException as exc:
            raise TavilyUnavailable("Tavily request timed out") from exc
        except httpx.RequestError as exc:
            raise TavilyUnavailable(f"Tavily network error: {exc}") from exc

        if r.status_code == 401:
            raise TavilyAuthError("Invalid TAVILY_API_KEY")
        if r.status_code == 429:
            raise TavilyUnavailable("Tavily rate limit hit — slow down or upgrade plan")
        if not r.is_success:
            raise TavilyUnavailable(f"Tavily returned HTTP {r.status_code}: {r.text[:200]}")

        return r.json()


__all__ = ["TavilyAuthError", "TavilyAuthMissing", "TavilyUnavailable", "tavily_search"]
