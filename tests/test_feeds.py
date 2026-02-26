import httpx
import pytest

from checks.feeds import FeedsCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_feeds_structured_alternate_link_scores_full():
    check = FeedsCheck()
    html = """
    <html><head>
      <link rel='alternate' type='application/atom+xml' href='/catalog/products.atom'>
    </head></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert "/catalog/products.atom" in result.details["structured_feed_hrefs"]


@pytest.mark.asyncio
async def test_feeds_generic_alternate_link_scores_partial():
    check = FeedsCheck()
    html = """
    <html><head>
      <link rel='alternate' type='application/rss+xml' href='/news.xml'>
    </head></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL
    assert "/news.xml" in result.details["alternate_feed_hrefs"]


@pytest.mark.asyncio
async def test_feeds_google_shopping_hint_counts_as_structured():
    check = FeedsCheck()
    html = "<html><body>Upload this shopping feed to Google Shopping via Merchant Center.</body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 1.0
    assert result.details["google_shopping_hint"] is True


@pytest.mark.asyncio
async def test_feeds_missing_feed_links_scores_zero():
    check = FeedsCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<html></html>"}})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    assert result.details["alternate_feed_hrefs"] == []


@pytest.mark.asyncio
async def test_feeds_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = FeedsCheck()
    html = "<html><head><link rel='alternate' type='application/rss+xml' href='/feed.xml'></head></html>"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, html)}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 0.5
    assert "/feed.xml" in result.details["alternate_feed_hrefs"]
