import httpx
import pytest

from checks.structured_data import StructuredDataCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_structured_data_product_jsonld_scores_full():
    check = StructuredDataCheck()
    html = """
    <html><head>
      <script type='application/ld+json'>
        {"@context":"https://schema.org","@type":"Product","name":"Widget","offers":{"@type":"Offer","price":"19.99","availability":"https://schema.org/InStock"}}
      </script>
      <meta property='og:title' content='Widget'>
      <meta property='og:type' content='product'>
      <meta property='og:image' content='https://example.com/widget.jpg'>
    </head></html>
    """
    artifacts = {"index": {"status_code": 200, "text": html}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert "Product" in result.details["schema_types"]
    assert any(s.name == "schema:Product" for s in result.signals)


@pytest.mark.asyncio
async def test_structured_data_og_only_scores_half():
    check = StructuredDataCheck()
    html = """
    <html><head>
      <meta property='og:title' content='Store'>
      <meta property='og:type' content='website'>
      <meta property='og:image' content='https://example.com/image.jpg'>
    </head></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL
    assert "Product" not in result.details["schema_types"]


@pytest.mark.asyncio
async def test_structured_data_non_product_jsonld_scores_three_quarters():
    check = StructuredDataCheck()
    html = """
    <html><head>
      <script type='application/ld+json'>
        {"@graph":[{"@type":"Organization","name":"Shop Co"},{"@type":"WebSite","name":"Shop"}]}
      </script>
    </head></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.75
    assert result.severity == Severity.PARTIAL
    assert sorted(result.details["schema_types"]) == ["Organization", "WebSite"]


@pytest.mark.asyncio
async def test_structured_data_malformed_jsonld_with_no_og_fails():
    check = StructuredDataCheck()
    html = "<script type='application/ld+json'>{not valid json}</script>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    assert result.details["malformed_json_ld_blocks"] == 1


@pytest.mark.asyncio
async def test_structured_data_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = StructuredDataCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/": (
                    200,
                    "<meta property='og:title' content='Fetched'><meta property='og:type' content='website'>",
                )
            }
        ),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 0.5
    assert any(name == "og:title" for name in result.details["open_graph_tags"])
