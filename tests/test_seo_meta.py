import httpx
import pytest

from checks.seo_meta import SeoMetaCheck
from core.models import Severity


def _perfect_html() -> str:
    return """
    <html lang='en'>
      <head>
        <title>Quality Running Shoes for Trail and Road</title>
        <meta name='description' content='Shop durable running shoes for trail and road with fast shipping, easy returns, and trusted customer reviews.'>
        <link rel='canonical' href='https://example.com/'>
        <meta name='viewport' content='width=device-width, initial-scale=1'>
      </head>
      <body>
        <h1>Running Shoes</h1>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_seo_meta_perfect_html_scores_full():
    check = SeoMetaCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _perfect_html()}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert {signal.name for signal in result.signals} == {"title", "description", "canonical", "language", "viewport", "h1"}


@pytest.mark.asyncio
async def test_seo_meta_empty_html_scores_zero():
    check = SeoMetaCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": ""}})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    assert all(signal.value == "missing" for signal in result.signals)


@pytest.mark.asyncio
async def test_seo_meta_missing_description_reduces_score():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<meta name='description' content='Shop durable running shoes for trail and road with fast shipping, easy returns, and trusted customer reviews.'>", "")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5 / 6)
    assert next(s for s in result.signals if s.name == "description").severity == Severity.FAIL
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_seo_meta_title_too_long_scores_partial_for_title():
    check = SeoMetaCheck()
    long_title = "X" * 71
    html = _perfect_html().replace("Quality Running Shoes for Trail and Road", long_title)

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5.5 / 6)
    assert next(s for s in result.signals if s.name == "title").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_seo_meta_multiple_h1_scores_partial_for_h1():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<h1>Running Shoes</h1>", "<h1>Running Shoes</h1><h1>Featured Products</h1>")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5.5 / 6)
    assert next(s for s in result.signals if s.name == "h1").severity == Severity.PARTIAL
    assert result.details["h1_count"] == 2


@pytest.mark.asyncio
async def test_seo_meta_no_canonical_reduces_score():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<link rel='canonical' href='https://example.com/'>", "")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5 / 6)
    assert next(s for s in result.signals if s.name == "canonical").value == "missing"


@pytest.mark.asyncio
async def test_seo_meta_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = SeoMetaCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, _perfect_html())}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
