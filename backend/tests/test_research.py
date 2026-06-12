"""Tests for integrations/tavily.py and integrations/research.py (P2-2).

httpx is mocked (CLAUDE.md forbids live-integration tests); research.py is
exercised against a temp directory via monkeypatched settings.
"""

from __future__ import annotations

import httpx
import pytest

from lattice.integrations import research
from lattice.integrations.tavily import (
    TavilyAuthError,
    TavilyUnavailable,
    tavily_search,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


def _patch_post(monkeypatch, handler) -> None:
    class _Client:
        def __init__(self, *a, **k) -> None: ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a) -> None: ...

        async def post(self, url, json):  # noqa: A002
            return handler(url, json)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


@pytest.mark.asyncio
async def test_tavily_search_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict = {}

    def handler(url, payload):
        captured.update(payload)
        return _FakeResponse(200, {"results": [{"title": "x"}], "answer": "yes"})

    _patch_post(monkeypatch, handler)
    out = await tavily_search("teen sleep", api_key="k", max_results=3)
    assert out["answer"] == "yes"
    assert captured["query"] == "teen sleep"
    assert captured["max_results"] == 3
    assert captured["api_key"] == "k"


@pytest.mark.asyncio
async def test_tavily_search_auth_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_post(monkeypatch, lambda url, p: _FakeResponse(401))
    with pytest.raises(TavilyAuthError):
        await tavily_search("q", api_key="bad")


@pytest.mark.asyncio
async def test_tavily_search_rate_limit_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_post(monkeypatch, lambda url, p: _FakeResponse(429))
    with pytest.raises(TavilyUnavailable):
        await tavily_search("q", api_key="k")


@pytest.mark.asyncio
async def test_tavily_search_timeout(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def handler(url, payload):
        raise httpx.TimeoutException("slow")

    _patch_post(monkeypatch, handler)
    with pytest.raises(TavilyUnavailable):
        await tavily_search("q", api_key="k")


def test_research_save_list_read_roundtrip(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(research, "_research_dir", lambda: tmp_path)

    fname = research.save_paper(
        title="Teen Sleep & HRV",
        topic="sleep",
        content="# Findings\n\nadolescents need 8-10h.",
        sources=["https://example.com/a", "https://example.com/b"],
    )
    assert fname.endswith(".md")
    assert (tmp_path / fname).exists()

    papers = research.list_papers()
    assert len(papers) == 1
    assert papers[0]["title"] == "Teen Sleep & HRV"
    assert papers[0]["topic"] == "sleep"
    assert papers[0]["sources"] == ["https://example.com/a", "https://example.com/b"]

    # topic filter is case-insensitive
    assert research.list_papers(topic="SLEEP")
    assert research.list_papers(topic="nutrition") == []

    body = research.read_paper(fname)
    assert "adolescents need 8-10h" in body


def test_research_read_missing_raises(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(research, "_research_dir", lambda: tmp_path)
    with pytest.raises(FileNotFoundError):
        research.read_paper("nope.md")


def test_research_read_blocks_path_traversal(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(research, "_research_dir", lambda: tmp_path)
    # `..`-style names are reduced to their basename, so this resolves inside
    # the research dir (and is absent) rather than escaping it.
    with pytest.raises(FileNotFoundError):
        research.read_paper("../../etc/passwd")
