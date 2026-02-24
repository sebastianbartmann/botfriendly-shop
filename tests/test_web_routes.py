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
async def test_scan_normalizes_bare_domain():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan", data={"url": "vorwerk.de"}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "https://vorwerk.de"


@pytest.mark.asyncio
async def test_scan_keeps_existing_protocol():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan", data={"url": "http://vorwerk.de"}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "http://vorwerk.de"


@pytest.mark.asyncio
async def test_scan_strips_whitespace_before_normalizing():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/scan", data={"url": "  vorwerk.de  "}, follow_redirects=False)

    assert response.status_code == 303
    scan_id = _scan_id_from_location(response.headers["location"])
    assert scans[scan_id]["url"] == "https://vorwerk.de"
