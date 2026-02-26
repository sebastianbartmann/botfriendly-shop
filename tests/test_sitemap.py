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


def _sitemap_index(lastmod: str | None = None) -> str:
    lastmod_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<sitemap><loc>https://example.com/sitemap-products.xml</loc>{lastmod_tag}</sitemap>"
        "</sitemapindex>"
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
        "sitemap.xml": {
            "status_code": 200,
            "text": _sitemap(lastmod=fresh),
            "content_type": "application/xml",
            "final_url": "https://example.com/sitemap.xml",
        },
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
async def test_sitemap_lastmod_freshness_boundary_30_days_pass_31_days_partial():
    check = SitemapCheck()
    at_30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    at_31 = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()

    fresh_result = await check.run(
        "https://example.com",
        {"sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=at_30)}, "robots.txt": {"status_code": 200, "text": ""}},
    )
    stale_result = await check.run(
        "https://example.com",
        {"sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=at_31)}, "robots.txt": {"status_code": 200, "text": ""}},
    )

    assert fresh_result.score == 1.0
    assert fresh_result.severity == Severity.PASS
    assert stale_result.score == 0.5
    assert stale_result.severity == Severity.PARTIAL


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


@pytest.mark.asyncio
async def test_sitemap_valid_xml_with_zero_urls_is_partial():
    check = SitemapCheck()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(include_url=False)},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    has_urls = next(signal for signal in result.signals if signal.name == "has_urls")
    assert has_urls.value is False
    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_sitemap_index_counts_as_entries():
    check = SitemapCheck()
    fresh = datetime.now(timezone.utc).isoformat()
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap_index(lastmod=fresh)},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    has_urls = next(signal for signal in result.signals if signal.name == "has_urls")
    assert has_urls.value is True
    assert has_urls.detail == "sitemap index with 1 child sitemaps"
    assert result.details["sitemap_count"] == 1
    assert result.details["url_count"] == 0


@pytest.mark.asyncio
async def test_sitemap_empty_sitemapindex_is_partial():
    check = SitemapCheck()
    empty_index = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></sitemapindex>'
    )
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": empty_index},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    has_urls = next(signal for signal in result.signals if signal.name == "has_urls")
    assert has_urls.value is False
    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_sitemap_html_content_type_treated_as_missing():
    check = SitemapCheck()
    artifacts = {
        "sitemap.xml": {
            "status_code": 200,
            "text": "<html><body>App shell</body></html>",
            "content_type": "text/html; charset=utf-8",
            "final_url": "https://example.com/",
        },
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_sitemap_fetch_error_status_none_fails():
    check = SitemapCheck()
    artifacts = {
        "sitemap.xml": {"status_code": None, "text": "", "content_type": None, "final_url": None},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.INCONCLUSIVE


@pytest.mark.asyncio
async def test_sitemap_lastmod_with_z_suffix_parses_as_fresh():
    check = SitemapCheck()
    fresh_z = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=fresh_z)},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_sitemap_lastmod_with_timezone_offset_parses_as_fresh():
    check = SitemapCheck()
    fresh_offset = (datetime.now(timezone.utc) - timedelta(days=1)).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )
    artifacts = {
        "sitemap.xml": {"status_code": 200, "text": _sitemap(lastmod=fresh_offset.isoformat())},
        "robots.txt": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
