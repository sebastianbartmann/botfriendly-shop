import httpx
import pytest

from checks.semantic_html import SemanticHtmlCheck
from core.models import Severity


def _full_html() -> str:
    return """
    <html>
      <body>
        <header>
          <nav>
            <ul>
              <li><a href="/shop">Shop Running Shoes</a></li>
            </ul>
          </nav>
        </header>
        <main>
          <article>
            <h1>Running Shoes</h1>
            <section>
              <h2>Trail Collection</h2>
              <figure>
                <figcaption>Blue trail runner, waterproof upper</figcaption>
              </figure>
              <time datetime="2026-02-20">February 20, 2026</time>
            </section>
            <aside>
              <address>100 Market St, San Francisco, CA</address>
            </aside>
          </article>
        </main>
        <footer></footer>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_semantic_html_full_html_scores_full():
    check = SemanticHtmlCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _full_html()}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert len(result.signals) == 3
    assert {signal.name for signal in result.signals} == {
        "semantic_elements",
        "heading_hierarchy",
        "semantic_navigation_lists",
    }
    assert all(signal.name != "content_semantic_elements" for signal in result.signals)
    assert "content_semantic_elements" not in result.details


@pytest.mark.asyncio
async def test_semantic_html_empty_html_scores_low_and_fails():
    check = SemanticHtmlCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": ""}})

    assert result.severity == Severity.FAIL
    assert result.score < 0.4


@pytest.mark.asyncio
async def test_semantic_html_semantic_element_coverage_partial():
    check = SemanticHtmlCheck()
    html = "<html><body><header></header><main><h1>Title</h1></main></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_elements_used"] == ["header", "main"]
    assert next(s for s in result.signals if s.name == "semantic_elements").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_html_heading_hierarchy_with_skips_is_partial():
    check = SemanticHtmlCheck()
    html = "<html><body><h1>Title</h1><h3>Skipped h2</h3></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    heading = result.details["heading_hierarchy"]
    assert heading["skipped_transitions"] == 1
    assert heading["h1_count"] == 1
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_html_heading_hierarchy_multiple_h1_is_partial():
    check = SemanticHtmlCheck()
    html = """
    <html>
      <body>
        <header>
          <nav>
            <ul><li><a href="/shop">Shop</a></li></ul>
          </nav>
        </header>
        <main>
          <article>
            <h1>Title</h1>
            <section>
              <h2>Section</h2>
              <h1>Another</h1>
            </section>
            <aside>Related</aside>
          </article>
        </main>
        <footer>Footer</footer>
      </body>
    </html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["heading_hierarchy"]["h1_count"] == 2
    assert result.details["heading_hierarchy"]["message"] == "Multiple <h1> elements found; keep one primary heading when possible."
    assert next(s for s in result.signals if s.name == "heading_hierarchy").value == "h1=2, skips=0"
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL
    assert result.details["heading_hierarchy"]["starts_with_h1"] is True
    assert result.details["heading_hierarchy"]["starts_with_h2"] is False
    assert result.details["heading_hierarchy"]["summary"] == "h1=2, skips=0"
    assert result.details["heading_hierarchy"]["skipped_transitions"] == 0
    assert result.score == pytest.approx((1.0 + 0.75 + 1.0) / 3)


@pytest.mark.asyncio
async def test_semantic_html_heading_hierarchy_starting_at_h2_without_h1_is_lower_than_multiple_h1():
    check = SemanticHtmlCheck()
    html = "<html><body><h2>Section title</h2><h3>Details</h3><h4>Specs</h4></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    heading = result.details["heading_hierarchy"]
    assert heading["starts_with_h1"] is False
    assert heading["starts_with_h2"] is True
    assert heading["h1_count"] == 0
    assert heading["skipped_transitions"] == 0
    assert heading["summary"] == "h1=0, skips=0"
    assert heading["message"] == "Headings start at <h2> without a primary <h1>."
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL
    assert result.score == pytest.approx((0.25 + 0.0 + 0.0) / 3)


@pytest.mark.asyncio
async def test_semantic_html_nav_without_list_is_partial():
    check = SemanticHtmlCheck()
    html = "<html><body><nav><div><a href='/a'>A</a></div></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["navigation_regions"] == 1
    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 0
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_html_aria_nav_without_lists_is_mild_penalty():
    check = SemanticHtmlCheck()
    html = "<html><body><div role='navigation'><span><a href='/a'>A</a></span></div><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    nav = result.details["semantic_navigation_lists"]
    assert nav["navigation_regions"] == 1
    assert nav["semantic_navigation_regions"] == 0
    assert nav["summary"] == "regions=1, semantic=0"
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PARTIAL
    assert result.score == pytest.approx((0.0 + 1.0 + 0.75) / 3)


@pytest.mark.asyncio
async def test_semantic_html_nav_with_semantic_list_passes():
    check = SemanticHtmlCheck()
    html = "<html><body><nav><ul><li><a href='/a'>Products</a></li></ul></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 1
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_html_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = SemanticHtmlCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, _full_html())}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
