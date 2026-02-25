import httpx
import pytest

from checks.accessibility import AccessibilityCheck
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
            <figure>
              <img src="shoe.jpg" alt="Blue trail running shoe" />
              <figcaption>Blue trail runner, waterproof upper</figcaption>
            </figure>
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
async def test_accessibility_full_html_scores_full():
    check = AccessibilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": _full_html()}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert len(result.signals) == 6


@pytest.mark.asyncio
async def test_accessibility_empty_html_scores_low_and_fails():
    check = AccessibilityCheck()

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": ""}})

    assert result.severity == Severity.FAIL
    assert result.score < 0.4


@pytest.mark.asyncio
async def test_accessibility_image_alt_ratio_is_used():
    check = AccessibilityCheck()
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
async def test_accessibility_landmarks_detected_from_roles():
    check = AccessibilityCheck()
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
async def test_accessibility_form_labels_partial_when_one_missing():
    check = AccessibilityCheck()
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
async def test_accessibility_form_labels_accepts_aria_label():
    check = AccessibilityCheck()
    html = "<html><body><h1>Title</h1><input aria-label='Search products'></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["form_labels"]["ratio"] == 1.0
    assert next(s for s in result.signals if s.name == "form_labels").severity == Severity.PASS


@pytest.mark.asyncio
async def test_accessibility_link_quality_flags_generic_text():
    check = AccessibilityCheck()
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
async def test_accessibility_skip_navigation_detected():
    check = AccessibilityCheck()
    html = "<html><body><a href='#content'>Skip to content</a><h1>Title</h1></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["skip_navigation"]["present"] is True
    assert next(s for s in result.signals if s.name == "skip_navigation").severity == Severity.PASS


@pytest.mark.asyncio
async def test_accessibility_skip_navigation_missing_is_fail_signal():
    check = AccessibilityCheck()
    html = "<html><body><h1>Title</h1><a href='#details'>Jump to details</a></body></html>"

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.details["skip_navigation"]["present"] is False
    assert next(s for s in result.signals if s.name == "skip_navigation").severity == Severity.FAIL


@pytest.mark.asyncio
async def test_accessibility_table_accessibility_partial_without_scope():
    check = AccessibilityCheck()
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
async def test_accessibility_table_accessibility_pass_with_complete_headers():
    check = AccessibilityCheck()
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
async def test_accessibility_fetches_index_when_missing(monkeypatch, fake_get_factory):
    check = AccessibilityCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/": (200, _full_html())}),
        raising=True,
    )

    result = await check.run("https://example.com", {})

    assert result.score == 1.0
    assert result.severity == Severity.PASS
