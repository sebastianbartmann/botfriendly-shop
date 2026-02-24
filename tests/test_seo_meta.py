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
@pytest.mark.parametrize(
    "title_len,expected_title_severity,expected_score",
    [
        (10, Severity.PASS, 1.0),
        (9, Severity.PARTIAL, 5.5 / 6),
        (70, Severity.PASS, 1.0),
        (71, Severity.PARTIAL, 5.5 / 6),
    ],
)
async def test_seo_meta_title_length_boundaries(title_len, expected_title_severity, expected_score):
    check = SeoMetaCheck()
    html = _perfect_html().replace("Quality Running Shoes for Trail and Road", "T" * title_len)

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(expected_score)
    assert next(s for s in result.signals if s.name == "title").severity == expected_title_severity


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "desc_len,expected_desc_severity,expected_score",
    [
        (50, Severity.PASS, 1.0),
        (49, Severity.PARTIAL, 5.5 / 6),
        (160, Severity.PASS, 1.0),
        (161, Severity.PARTIAL, 5.5 / 6),
    ],
)
async def test_seo_meta_description_length_boundaries(desc_len, expected_desc_severity, expected_score):
    check = SeoMetaCheck()
    html = _perfect_html().replace(
        "Shop durable running shoes for trail and road with fast shipping, easy returns, and trusted customer reviews.",
        "D" * desc_len,
    )

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(expected_score)
    assert next(s for s in result.signals if s.name == "description").severity == expected_desc_severity


@pytest.mark.asyncio
async def test_seo_meta_multiple_h1_scores_partial_for_h1():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<h1>Running Shoes</h1>", "<h1>Running Shoes</h1><h1>Featured Products</h1>")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5.5 / 6)
    assert next(s for s in result.signals if s.name == "h1").severity == Severity.PARTIAL
    assert result.details["h1_count"] == 2


@pytest.mark.asyncio
async def test_seo_meta_zero_h1_scores_fail_for_h1():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<h1>Running Shoes</h1>", "")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5 / 6)
    assert result.details["h1_count"] == 0
    assert next(s for s in result.signals if s.name == "h1").severity == Severity.FAIL


@pytest.mark.asyncio
async def test_seo_meta_h1_more_than_one_has_half_contribution():
    check = SeoMetaCheck()
    html = _perfect_html().replace("<h1>Running Shoes</h1>", "<h1>Running Shoes</h1><h1>Featured Products</h1>")

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == pytest.approx(5.5 / 6)
    assert result.details["h1_count"] == 2
    assert next(s for s in result.signals if s.name == "h1").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_seo_meta_overall_severity_threshold_at_point_8_is_pass(monkeypatch):
    check = SeoMetaCheck()

    def _fake_length_score(value: str, min_len: int, max_len: int) -> float:  # noqa: ARG001
        return 0.4000000000000001 if value else 0.0

    monkeypatch.setattr(SeoMetaCheck, "_length_scored_value", staticmethod(_fake_length_score))
    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _perfect_html()}})

    assert result.score == pytest.approx(0.8)
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_seo_meta_overall_severity_below_point_8_is_partial(monkeypatch):
    check = SeoMetaCheck()

    def _fake_length_score(value: str, min_len: int, max_len: int) -> float:  # noqa: ARG001
        return 0.37 if value else 0.0

    monkeypatch.setattr(SeoMetaCheck, "_length_scored_value", staticmethod(_fake_length_score))
    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _perfect_html()}})

    assert result.score == pytest.approx(0.79)
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_seo_meta_missing_all_metadata_scores_zero():
    check = SeoMetaCheck()
    html = "<html><head></head><body><div>No seo metadata</div></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


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
