from __future__ import annotations

import httpx
import pytest

from web_app import admin_routes
from web_app.main import app


@pytest.fixture(autouse=True)
def admin_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "changeme")
    admin_routes._batch_task = None
    admin_routes._cancel_token = None
    admin_routes._progress_queue = None
    admin_routes._batch_summary = None
    yield
    admin_routes._batch_task = None
    admin_routes._cancel_token = None
    admin_routes._progress_queue = None
    admin_routes._batch_summary = None


@pytest.mark.asyncio
async def test_admin_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_wrong_password():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin", auth=("admin", "wrong"))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_ok():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/admin", auth=("admin", "changeme"))
    assert response.status_code == 200
    assert "Admin" in response.text


@pytest.mark.asyncio
async def test_batch_start_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/admin/batch/start", data={"urls": "https://example.com"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_batch_cancel_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/admin/batch/cancel")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_batch_start_no_urls():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/admin/batch/start",
            data={"urls": "\n\n# comment only"},
            auth=("admin", "changeme"),
        )
    assert response.status_code == 400
    assert response.json() == {"error": "no URLs provided"}


@pytest.mark.asyncio
async def test_batch_cancel_no_batch():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/admin/batch/cancel", auth=("admin", "changeme"))
    assert response.status_code == 200
    assert response.json() == {"status": "cancelling"}
