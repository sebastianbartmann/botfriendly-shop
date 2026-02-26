from __future__ import annotations

import httpx
import pytest

from web_app.main import app
from web_app.routes import scans


@pytest.fixture(autouse=True)
def clear_scans():
    scans.clear()
    yield
    scans.clear()


def _scan_id_from_location(location: str) -> str:
    return location.rsplit("/", 1)[1]


@pytest.mark.asyncio
async def test_home_page_renders():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scan_normalizes_bare_domain():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan?force=true", data={"url": "example.com"}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_scan_keeps_existing_protocol():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan?force=true", data={"url": "http://example.com"}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "http://example.com"


@pytest.mark.asyncio
async def test_scan_strips_whitespace_before_normalizing():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan?force=true", data={"url": "  example.com  "}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_results_page_for_nonexistent_scan_returns_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/results/nonexistent-id")

    assert response.status_code == 404
    assert "Page not found" in response.text


@pytest.mark.asyncio
async def test_scan_rejects_empty_url():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan", data={"url": ""}, follow_redirects=False)

    assert response.status_code == 400
    assert "URL is required" in response.text


@pytest.mark.asyncio
async def test_bots_page_renders():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/bots")

    assert response.status_code == 200
    assert "AI Bots We Check For" in response.text
    assert "AI Shopping Agents" in response.text
    assert "AI Search Indexers &amp; Retrieval" in response.text
    assert "AI Training Crawlers" in response.text


@pytest.mark.asyncio
async def test_category_info_page_renders():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/results/info/robots")

    assert response.status_code == 200
    assert "Robots.txt AI Bot Access" in response.text
    assert "Field Guide" in response.text


@pytest.mark.asyncio
async def test_category_info_page_unknown_category_returns_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/results/info/not-real")

    assert response.status_code == 404
    assert "Page not found" in response.text
