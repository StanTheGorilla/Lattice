"""API tests for the /api/journal endpoints.

Web-UI parity for the AI-journal store. Uses an isolated in-memory SQLite
session injected via FastAPI dependency override; auth is permissive in dev
(no WEB_UI_PASSWORD), so no header is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from lattice.db import get_session
from lattice.main import app
from lattice.models import Base


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/journal")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_create_then_list(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/journal",
        json={"entry": "prefers terse replies", "kind": "correction"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["entry"] == "prefers terse replies"
    assert created["kind"] == "correction"
    assert created["weight"] == 1
    assert created["active"] is True

    listing = (await client.get("/api/journal")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_patch_updates_field(client: AsyncClient) -> None:
    created = (
        await client.post("/api/journal", json={"entry": "note one"})
    ).json()
    assert created["kind"] == "observation"
    resp = await client.patch(
        f"/api/journal/{created['id']}", json={"active": False},
    )
    assert resp.status_code == 200
    patched = resp.json()
    assert patched["active"] is False
    assert patched["entry"] == "note one"
    assert patched["updated_at"] >= created["updated_at"]


@pytest.mark.asyncio
async def test_patch_missing_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/journal/999", json={"active": False})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


@pytest.mark.asyncio
async def test_delete_then_gone(client: AsyncClient) -> None:
    created = (
        await client.post("/api/journal", json={"entry": "ephemeral"})
    ).json()
    resp = await client.delete(f"/api/journal/{created['id']}")
    assert resp.status_code == 204

    listing = (await client.get("/api/journal")).json()
    assert listing["total"] == 0
    assert (await client.delete(f"/api/journal/{created['id']}")).status_code == 404
