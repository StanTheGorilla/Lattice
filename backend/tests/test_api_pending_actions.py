"""API tests for the /api/pending-actions endpoints.

Web-UI parity for the open-commitments store. Uses an isolated in-memory
SQLite session injected via FastAPI dependency override; auth is permissive in
dev (no WEB_UI_PASSWORD), so no header is needed.
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
    resp = await client.get("/api/pending-actions")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_create_then_list(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/pending-actions",
        json={"summary": "email coach", "detail": "send weekly recap"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["summary"] == "email coach"
    assert created["detail"] == "send weekly recap"
    assert created["status"] == "open"
    assert created["created_at"] == created["updated_at"]

    listing = (await client.get("/api/pending-actions")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_patch_updates_field(client: AsyncClient) -> None:
    created = (
        await client.post("/api/pending-actions", json={"summary": "task"})
    ).json()
    resp = await client.patch(
        f"/api/pending-actions/{created['id']}", json={"status": "done"},
    )
    assert resp.status_code == 200
    patched = resp.json()
    assert patched["status"] == "done"
    assert patched["summary"] == "task"
    assert patched["updated_at"] >= created["updated_at"]


@pytest.mark.asyncio
async def test_patch_missing_404(client: AsyncClient) -> None:
    resp = await client.patch("/api/pending-actions/999", json={"status": "done"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "not_found"


@pytest.mark.asyncio
async def test_delete_then_gone(client: AsyncClient) -> None:
    created = (
        await client.post("/api/pending-actions", json={"summary": "drop me"})
    ).json()
    resp = await client.delete(f"/api/pending-actions/{created['id']}")
    assert resp.status_code == 204

    listing = (await client.get("/api/pending-actions")).json()
    assert listing["total"] == 0
    assert (
        await client.delete(f"/api/pending-actions/{created['id']}")
    ).status_code == 404
