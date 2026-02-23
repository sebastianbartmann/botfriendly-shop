from datetime import datetime, timedelta, timezone

import pytest

from checks.sitemap import SitemapCheck
from core.models import Severity


def _sitemap(lastmod: str | None = None, include_url: bool = True) -> str:
    lastmod_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    url_block = f"<url><loc>https://example.com/a</loc>{lastmod_tag}</url>" if include_url else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{url_block}"
        "</urlset>"
    )


@pytest.mark.asyncio
async def test_sitemap_missing():
    check = SitemapCheck()
    artifacts = {"sitemap.xml": {"status_code": 404, "text": ""}, "robots.txt": {"status_code": 200, "text": ""}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_sitemap_valid_and_fresh():
    check = SitemapCheck()
    fresh = datetime.now(timezone.utc).isoformat()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=fresh)},
        "robots.txt": {"status_code": 200, "text": "Sitemap: https://example.com/sitemap.xml"},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_sitemap_exists_but_invalid_xml():
    check = SitemapCheck()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": "<urlset><url>"},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_sitemap_old_lastmod_partial():
    check = SitemapCheck()
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=old)},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_sitemap_no_lastmod_partial():
    check = SitemapCheck()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=None)},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL
