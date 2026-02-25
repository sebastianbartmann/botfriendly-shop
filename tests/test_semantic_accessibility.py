import httpx
import pytest

from checks.semantic_accessibility import SemanticAccessibilityCheck
from core.models import Severity


def _full_html() -> str:
    return """
    <html>
      <body>
        <a href="#main-content" class="skip-link">Skip to main content</a>
        <header>
          <nav>
            <ul>
              <li><a href="/shop">Shop Running Shoes</a></li>
              <li><a href="/about">About the Brand</a></li>
            </ul>
          </nav>
        </header>
        <main id="main-content">
          <article>
            <h1>Running Shoes</h1>
            <section>
              <h2>Trail Collection</h2>
              <figure>
                <img src="shoe.jpg" alt="Blue trail running shoe" />
                <figcaption>Blue trail runner, waterproof upper</figcaption>
              </figure>
              <time datetime="2026-02-20">February 20, 2026</time>
            </section>
            <aside>
              <address>100 Market St, San Francisco, CA</address>
            </aside>
            <form>
              <label for="email">Email</label>
              <input id="email" type="email" />
            </form>
            <table>
              <thead>
                <tr>
                  <th scope="col">Size</th>
                  <th scope="col">Stock</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">9</th>
                  <td>In stock</td>
                </tr>
              </tbody>
            </table>
          </article>
        </main>
        <footer></footer>
      </body>
    </html>
    """


@pytest.mark.asyncio
async def test_semantic_accessibility_full_html_scores_full():
    check = SemanticAccessibilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _full_html()}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert len(result.signals) == 10


@pytest.mark.asyncio
async def test_semantic_accessibility_empty_html_scores_low_and_fails():
    check = SemanticAccessibilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": ""}})

    assert result.severity == Severity.FAIL
    assert result.score < 0.4


@pytest.mark.asyncio
async def test_semantic_accessibility_semantic_element_coverage_partial():
    check = SemanticAccessibilityCheck()
    html = "<html><body><header></header><main><h1>Title</h1></main></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_elements_used"] == ["header", "main"]
    assert next(s for s in result.signals if s.name == "semantic_elements").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_heading_hierarchy_with_skips_is_partial():
    check = SemanticAccessibilityCheck()
    html = "<html><body><h1>Title</h1><h3>Skipped h2</h3></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    heading = result.details["heading_hierarchy"]
    assert heading["skipped_transitions"] == 1
    assert heading["h1_count"] == 1
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_heading_hierarchy_multiple_h1_is_partial():
    check = SemanticAccessibilityCheck()
    html = "<html><body><h1>Title</h1><h2>Section</h2><h1>Another</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["heading_hierarchy"]["h1_count"] == 2
    assert next(s for s in result.signals if s.name == "heading_hierarchy").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_nav_without_list_is_partial():
    check = SemanticAccessibilityCheck()
    html = "<html><body><nav><div><a href='/a'>A</a></div></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["navigation_regions"] == 1
    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 0
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_nav_with_semantic_list_passes():
    check = SemanticAccessibilityCheck()
    html = "<html><body><nav><ul><li><a href='/a'>Products</a></li></ul></nav><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["semantic_navigation_lists"]["semantic_navigation_regions"] == 1
    assert next(s for s in result.signals if s.name == "semantic_navigation_lists").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_accessibility_content_semantic_elements_partial():
    check = SemanticAccessibilityCheck()
    html = "<html><body><h1>Title</h1><figure></figure><time datetime='2026-01-01'>Jan 1</time></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    details = result.details["content_semantic_elements"]
    assert set(details["present"]) == {"figure", "time"}
    assert next(s for s in result.signals if s.name == "content_semantic_elements").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_image_alt_ratio_is_used():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body><h1>Title</h1>
      <img src='a.jpg' alt='A shoe'>
      <img src='b.jpg' alt=''>
      <img src='c.jpg'>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["image_alt_text"]["with_alt"] == 1
    assert result.details["image_alt_text"]["total_images"] == 3
    assert next(s for s in result.signals if s.name == "image_alt_text").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_landmarks_detected_from_roles():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body>
      <div role='banner'></div>
      <div role='navigation'></div>
      <div role='main'></div>
      <div role='contentinfo'></div>
      <h1>Title</h1>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["landmarks"]["present_count"] == 4
    assert next(s for s in result.signals if s.name == "landmarks").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_accessibility_form_labels_partial_when_one_missing():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body><h1>Title</h1>
      <form>
        <label for='q'>Query</label><input id='q'>
        <input id='no-label'>
      </form>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["form_labels"]["labeled_inputs"] == 1
    assert result.details["form_labels"]["total_inputs"] == 2
    assert next(s for s in result.signals if s.name == "form_labels").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_form_labels_accepts_aria_label():
    check = SemanticAccessibilityCheck()
    html = "<html><body><h1>Title</h1><input aria-label='Search products'></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["form_labels"]["ratio"] == 1.0
    assert next(s for s in result.signals if s.name == "form_labels").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_accessibility_link_quality_flags_generic_text():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body><h1>Title</h1>
      <a href='/a'>click here</a>
      <a href='/b'>Read more</a>
      <a href='/c'>View winter running collection</a>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["link_quality"]["descriptive_links"] == 1
    assert result.details["link_quality"]["total_links"] == 3
    assert next(s for s in result.signals if s.name == "link_quality").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_skip_navigation_detected():
    check = SemanticAccessibilityCheck()
    html = "<html><body><a href='#content'>Skip to content</a><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["skip_navigation"]["present"] is True
    assert next(s for s in result.signals if s.name == "skip_navigation").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_accessibility_skip_navigation_missing_is_fail_signal():
    check = SemanticAccessibilityCheck()
    html = "<html><body><h1>Title</h1><a href='#details'>Jump to details</a></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["skip_navigation"]["present"] is False
    assert next(s for s in result.signals if s.name == "skip_navigation").severity == Severity.FAIL


@pytest.mark.asyncio
async def test_semantic_accessibility_table_accessibility_partial_without_scope():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body><h1>Title</h1>
      <table>
        <thead><tr><th>Col A</th></tr></thead>
        <tbody><tr><td>Value</td></tr></tbody>
      </table>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["table_accessibility"]["table_count"] == 1
    assert result.details["table_accessibility"]["accessible_tables"] == 0
    assert next(s for s in result.signals if s.name == "table_accessibility").severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_semantic_accessibility_table_accessibility_pass_with_complete_headers():
    check = SemanticAccessibilityCheck()
    html = """
    <html><body><h1>Title</h1>
      <table>
        <thead><tr><th scope='col'>Col A</th></tr></thead>
        <tbody><tr><th scope='row'>Row 1</th></tr></tbody>
      </table>
    </body></html>
    """

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["table_accessibility"]["accessible_tables"] == 1
    assert next(s for s in result.signals if s.name == "table_accessibility").severity == Severity.PASS


@pytest.mark.asyncio
async def test_semantic_accessibility_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = SemanticAccessibilityCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, _full_html())}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
