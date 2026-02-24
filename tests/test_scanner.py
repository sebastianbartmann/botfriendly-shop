import httpx
import pytest

from checks.base import BaseCheck
from core.models import CheckResult, Severity
from core.scanner import Scanner


class StubCheck(BaseCheck):
    def __init__(self, name: str, score: float):
        self.name = name
        self._score = score

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        return CheckResult(category=self.name, score=self._score, severity=Severity.PASS, details={"seen": sorted(artifacts.keys())})


@pytest.mark.asyncio
async def test_scanner_average_score_with_stub_checks(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                f"{base}": (404, ""),
                f"{base}robots.txt": (404, ""),
                f"{base}sitemap.xml": (404, ""),
                f"{base}llms.txt": (404, ""),
                f"{base}llms-full.txt": (404, ""),
                f"{base}.well-known/ai-plugin.json": (404, ""),
                f"{base}.well-known/agent.json": (404, ""),
                f"{base}.well-known/mcp.json": (404, ""),
            }
        ),
        raising=True,
    )
    scanner = Scanner(checks=[StubCheck("a", 1.0), StubCheck("b", 0.5), StubCheck("c", 0.0)])

    result = await scanner.scan("https://example.com")

    assert result.overall_score == pytest.approx(0.5)
    assert result.metadata["grade"] == "C"
    assert len(result.check_results) == 3


@pytest.mark.asyncio
async def test_scanner_handles_no_checks(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                f"{base}": (404, ""),
                f"{base}robots.txt": (404, ""),
                f"{base}sitemap.xml": (404, ""),
                f"{base}llms.txt": (404, ""),
                f"{base}llms-full.txt": (404, ""),
                f"{base}.well-known/ai-plugin.json": (404, ""),
                f"{base}.well-known/agent.json": (404, ""),
                f"{base}.well-known/mcp.json": (404, ""),
            }
        ),
        raising=True,
    )
    scanner = Scanner(checks=[])

    result = await scanner.scan("https://example.com")

    assert result.overall_score == 0.0
    assert result.metadata["grade"] == "F"
    assert result.check_results == []


@pytest.mark.asyncio
async def test_scanner_http_pass_fetches_common_files(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    route_map = {
        f"{base}": (200, "<html></html>"),
        f"{base}robots.txt": (200, "User-agent: *"),
        f"{base}sitemap.xml": (200, "<urlset></urlset>"),
        f"{base}llms.txt": (200, "ok"),
        f"{base}llms-full.txt": (404, ""),
        f"{base}.well-known/ai-plugin.json": (404, ""),
        f"{base}.well-known/agent.json": (404, ""),
        f"{base}.well-known/mcp.json": (404, ""),
    }
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get_factory(route_map), raising=True)

    scanner = Scanner(checks=[StubCheck("a", 1.0)])
    result = await scanner.scan("https://example.com")

    seen = result.check_results[0].details["seen"]
    assert "index" in seen
    assert "robots.txt" in seen
    assert "sitemap.xml" in seen
    assert ".well-known/agent.json" in seen


@pytest.mark.asyncio
async def test_scanner_http_pass_captures_content_type_and_final_url(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                f"{base}": (200, "<html></html>", "text/html; charset=utf-8", f"{base}"),
                f"{base}robots.txt": (200, "User-agent: *", "text/plain", f"{base}robots.txt"),
                f"{base}sitemap.xml": (200, "<urlset></urlset>", "application/xml", f"{base}sitemap.xml"),
                f"{base}llms.txt": (200, "ok", "text/plain", f"{base}llms.txt"),
                f"{base}llms-full.txt": (200, "ok", "text/plain", f"{base}llms-full.txt"),
                f"{base}.well-known/ai-plugin.json": (200, "{}", "application/json", f"{base}.well-known/ai-plugin.json"),
                f"{base}.well-known/agent.json": (200, "{}", "application/json", f"{base}.well-known/agent.json"),
                f"{base}.well-known/mcp.json": (200, "{}", "application/json", f"{base}.well-known/mcp.json"),
            }
        ),
        raising=True,
    )
    scanner = Scanner(checks=[])

    artifacts = await scanner._http_pass("https://example.com")

    assert artifacts["llms.txt"]["content_type"] == "text/plain"
    assert artifacts["llms.txt"]["final_url"] == "https://example.com/llms.txt"
    assert artifacts[".well-known/agent.json"]["content_type"] == "application/json"
    assert artifacts[".well-known/agent.json"]["final_url"] == "https://example.com/.well-known/agent.json"


@pytest.mark.asyncio
async def test_scanner_passes_url_to_checks(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({f"{base}{path}": (404, "") for path in ["", "robots.txt", "sitemap.xml", "llms.txt", "llms-full.txt", ".well-known/ai-plugin.json", ".well-known/agent.json", ".well-known/mcp.json"]}),
        raising=True,
    )

    class URLCheck(BaseCheck):
        async def run(self, url: str, artifacts: dict) -> CheckResult:
            return CheckResult(category="url", score=1.0, severity=Severity.PASS, details={"url": url})

    scanner = Scanner(checks=[URLCheck()])
    result = await scanner.scan("https://example.com")
    assert result.check_results[0].details["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_scanner_http_errors_are_tolerated(monkeypatch):
    async def _raise_http_error(self, url, *args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", _raise_http_error, raising=True)

    scanner = Scanner(checks=[StubCheck("a", 0.2)])
    result = await scanner.scan("https://example.com")

    assert result.overall_score == 0.2
    assert result.metadata["check_count"] == 1
    assert result.metadata["grade"] == "F"
