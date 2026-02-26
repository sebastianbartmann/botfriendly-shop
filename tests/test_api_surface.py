import httpx
import pytest

from checks.api_surface import APISurfaceCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_api_surface_openapi_json_scores_full(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/swagger.json": (404, ""), "https://example.com/openapi.yaml": (404, ""), "https://example.com/swagger.yaml": (404, ""), "https://example.com/api-docs": (404, "")}),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": "", "url": url})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)
    result = await check.run("https://example.com", {"openapi.json": {"status_code": 200, "text": "{}", "content_type": "application/json"}, "index": {"status_code": 200, "text": ""}})

    assert result.score == 1.0
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_api_surface_openapi_yaml_scores_full(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({"https://example.com/openapi.json": (404, ""), "https://example.com/swagger.json": (404, ""), "https://example.com/swagger.yaml": (404, ""), "https://example.com/api-docs": (404, "")}),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": "", "url": url})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)
    result = await check.run(
        "https://example.com",
        {"openapi.yaml": {"status_code": 200, "text": "openapi: 3.1.0", "content_type": "application/yaml"}, "index": {"status_code": 200, "text": ""}},
    )

    assert result.score == 1.0
    assert result.details["spec_found"]["/openapi.yaml"] is True


@pytest.mark.asyncio
async def test_api_surface_html_content_type_is_rejected_for_specs(monkeypatch):
    check = APISurfaceCheck()

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": "", "url": url})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)
    artifacts = {
        "openapi.json": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "openapi.yaml": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "swagger.json": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "swagger.yaml": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "api-docs": {"status_code": 404, "text": ""},
        "index": {"status_code": 200, "text": "<html></html>"},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.details["spec_found"]["/openapi.json"] is False
    assert result.details["spec_found"]["/openapi.yaml"] is False
    assert result.details["spec_found"]["/swagger.json"] is False
    assert result.details["spec_found"]["/swagger.yaml"] is False


@pytest.mark.asyncio
async def test_api_surface_doc_links_without_spec_scores_partial(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/openapi.yaml": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/swagger.yaml": (404, ""),
                "https://example.com/api-docs": (404, ""),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": "", "url": url})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)
    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<a href='/developer/docs'>Developer Docs</a>"}})

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_api_surface_graphql_options_counts_as_partial(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/openapi.yaml": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/swagger.yaml": (404, ""),
                "https://example.com/api-docs": (404, ""),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 204, "text": "", "url": "https://example.com/graphql"})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)
    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<html></html>"}})

    assert result.score == 0.5
    assert result.details["graphql_options_status"] == 204
