import httpx
import pytest

from checks.feeds import FeedsCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_feeds_structured_products_json_scores_full():
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 404, "text": ""},
        "feeds/products.atom": {"status_code": 404, "text": ""},
        "products.json": {"status_code": 200, "text": "[]"},
        "feed": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert result.details["found_paths"]["/products.json"] is True


@pytest.mark.asyncio
async def test_feeds_products_json_application_json_scores_full():
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 404, "text": ""},
        "feeds/products.atom": {"status_code": 404, "text": ""},
        "products.json": {"status_code": 200, "text": "[]", "content_type": "application/json"},
        "feed": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert result.details["found_paths"]["/products.json"] is True


@pytest.mark.asyncio
async def test_feeds_generic_rss_only_scores_half():
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 200, "text": "<rss />"},
        "feeds/products.atom": {"status_code": 404, "text": ""},
        "products.json": {"status_code": 404, "text": ""},
        "feed": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_feeds_not_found_scores_zero():
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 404, "text": ""},
        "feeds/products.atom": {"status_code": 404, "text": ""},
        "products.json": {"status_code": 404, "text": ""},
        "feed": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": "<html></html>"},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_feeds_detects_alternate_feed_link():
    check = FeedsCheck()
    html = """
    <html><head>
      <link rel='alternate' type='application/rss+xml' href='/feed.xml'>
    </head></html>
    """

    result = await check.run(
        "https://example.com",
        {
            "feed.xml": {"status_code": 404, "text": ""},
            "feeds/products.atom": {"status_code": 404, "text": ""},
            "products.json": {"status_code": 404, "text": ""},
            "feed": {"status_code": 404, "text": ""},
            "index": {"status_code": 200, "text": html},
        },
    )

    assert result.score == 0.5
    assert "/feed.xml" in result.details["alternate_feed_hrefs"]


@pytest.mark.asyncio
async def test_feeds_google_shopping_hint_counts_as_structured():
    check = FeedsCheck()
    html = "<html><body>Upload this shopping feed to Google Shopping via Merchant Center.</body></html>"

    result = await check.run(
        "https://example.com",
        {
            "feed.xml": {"status_code": 404, "text": ""},
            "feeds/products.atom": {"status_code": 404, "text": ""},
            "products.json": {"status_code": 404, "text": ""},
            "feed": {"status_code": 404, "text": ""},
            "index": {"status_code": 200, "text": html},
        },
    )

    assert result.score == 1.0
    assert result.details["google_shopping_hint"] is True


@pytest.mark.asyncio
async def test_feeds_fetches_missing_artifacts(monkeypatch, fake_get_factory):
    check = FeedsCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/feed.xml": (404, ""),
                "https://example.com/feeds/products.atom": (200, "<feed />"),
                "https://example.com/products.json": (404, ""),
                "https://example.com/feed": (404, ""),
                "https://example.com/": (200, ""),
            }
        ),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
    assert result.details["found_paths"]["/feeds/products.atom"] is True


@pytest.mark.asyncio
async def test_feeds_html_content_type_is_rejected():
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "feeds/products.atom": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "products.json": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "feed": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "index": {"status_code": 200, "text": "<html></html>"},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.details["found_paths"]["/feed.xml"] is False
    assert result.details["found_paths"]["/feeds/products.atom"] is False
    assert result.details["found_paths"]["/products.json"] is False
    assert result.details["found_paths"]["/feed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "artifact_key,path",
    [
        ("feed.xml", "/feed.xml"),
        ("feeds/products.atom", "/feeds/products.atom"),
        ("products.json", "/products.json"),
        ("feed", "/feed"),
    ],
)
async def test_feeds_html_content_type_rejected_per_path(artifact_key, path):
    check = FeedsCheck()
    artifacts = {
        "feed.xml": {"status_code": 404, "text": ""},
        "feeds/products.atom": {"status_code": 404, "text": ""},
        "products.json": {"status_code": 404, "text": ""},
        "feed": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": "<html></html>"},
    }
    artifacts[artifact_key] = {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.details["found_paths"][path] is False
