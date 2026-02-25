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
    assert len(result.signals) == 4


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
    html = "<html><body><h1>Title</h1><h2>Section</h2><h1>Another</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["heading_hierarchy"]["h1_count"] == 2
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_html_nav_without_list_is_partial():
    check = SemanticHtmlCheck()
    html = "<html><body><nav><div><a href='/a'>A</a></div></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["navigation_regions"] == 1
    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 0
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_html_nav_with_semantic_list_passes():
    check = SemanticHtmlCheck()
    html = "<html><body><nav><ul><li><a href='/a'>Products</a></li></ul></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 1
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_html_content_semantic_elements_partial():
    check = SemanticHtmlCheck()
    html = "<html><body><h1>Title</h1><figure></figure><time datetime='2026-01-01'>Jan 1</time></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    details = result.details["content_semantic_elements"]
    assert set(details["present"]) == {"figure", "time"}
    assert next(s for s in result.signals if s.name == "content_semantic_elements").severity == Severity.PARTIAL


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
