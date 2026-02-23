import httpx
import pytest

from checks.product_parseability import ProductParseabilityCheck
from core.models import Severity


def _rich_product_html(price: str = "19.99", og_price: str = "19.99") -> str:
    return f"""
    <html>
      <head>
        <script type='application/ld+json'>
          {{
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Widget",
            "offers": {{
              "@type": "Offer",
              "price": "{price}",
              "availability": "https://schema.org/InStock"
            }}
          }}
        </script>
        <meta property='og:title' content='Widget'>
        <meta property='og:price:amount' content='{og_price}'>
        <meta property='og:price:currency' content='USD'>
      </head>
      <body>
        <h1>Widget</h1>
        <span class='price'>${price}</span>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_product_parseability_rich_consistent_scores_full():
    check = ProductParseabilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _rich_product_html()}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert result.details["price_consistent"] is True


@pytest.mark.asyncio
async def test_product_parseability_no_data_scores_zero():
    check = ProductParseabilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<html></html>"}})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_product_parseability_partial_jsonld_scores_partial():
    check = ProductParseabilityCheck()
    html = """
    <html><head>
      <script type='application/ld+json'>{"@type":"Product","name":"Widget"}</script>
    </head><body><h1>Widget</h1></body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_product_parseability_price_mismatch_scores_partial():
    check = ProductParseabilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _rich_product_html(price="19.99", og_price="24.99")}})

    assert result.score == 0.5
    assert result.details["price_consistent"] is False


@pytest.mark.asyncio
async def test_product_parseability_malformed_jsonld_but_meta_partial():
    check = ProductParseabilityCheck()
    html = """
    <html><head>
      <script type='application/ld+json'>{bad json</script>
      <meta property='og:title' content='Widget'>
      <meta property='og:price:amount' content='19.99'>
      <meta property='og:price:currency' content='USD'>
    </head><body><h1>Widget</h1></body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.5
    assert result.details["malformed_json_ld_blocks"] == 1


@pytest.mark.asyncio
async def test_product_parseability_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = ProductParseabilityCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, _rich_product_html())}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
