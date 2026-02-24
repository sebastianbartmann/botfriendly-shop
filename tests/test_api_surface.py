import httpx
import pytest

from checks.api_surface import APISurfaceCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_api_surface_openapi_spec_scores_full(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get_factory({"https://example.com/api-docs": (404, "")}), raising=True)

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    artifacts = {"openapi.json": {"status_code": 200, "text": "{}"}, "index": {"status_code": 200, "text": ""}}
    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS


@pytest.mark.asyncio
async def test_api_surface_swagger_spec_scores_full(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({
            "https://example.com/openapi.json": (404, ""),
            "https://example.com/api-docs": (404, ""),
            "https://example.com/api/v1": (404, ""),
            "https://example.com/api/v2": (404, ""),
        }),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    artifacts = {"swagger.json": {"status_code": 200, "text": "{}"}, "index": {"status_code": 200, "text": ""}}
    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0


@pytest.mark.asyncio
async def test_api_surface_doc_links_without_spec_scores_partial(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/api-docs": (404, ""),
                "https://example.com/api/v1": (404, ""),
                "https://example.com/api/v2": (404, ""),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    html = "<a href='/developer/docs'>Developer Docs</a>"
    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": html}})

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_api_surface_nothing_found_scores_zero(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/api-docs": (404, ""),
                "https://example.com/api/v1": (404, ""),
                "https://example.com/api/v2": (404, ""),
                "https://example.com/": (200, "<html></html>"),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    result = await check.run("https://example.com", {})

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_api_surface_graphql_options_counts_as_partial(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/api-docs": (404, ""),
                "https://example.com/api/v1": (404, ""),
                "https://example.com/api/v2": (404, ""),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<html></html>"}})

    assert result.score == 0.5
    assert result.details["graphql_options_status"] == 204


@pytest.mark.asyncio
async def test_api_surface_fetches_missing_spec(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (200, "{}"),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/api-docs": (404, ""),
                "https://example.com/api/v1": (404, ""),
                "https://example.com/api/v2": (404, ""),
                "https://example.com/": (200, "<html></html>"),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    result = await check.run("https://example.com", {})

    assert result.score == 1.0


@pytest.mark.asyncio
async def test_api_surface_html_content_type_is_rejected_for_json_and_api_paths(monkeypatch):
    check = APISurfaceCheck()

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": ""})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    artifacts = {
        "openapi.json": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "swagger.json": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "api-docs": {"status_code": 404, "text": ""},
        "api/v1": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "api/v2": {"status_code": 200, "text": "<html>login</html>", "content_type": "text/html; charset=utf-8"},
        "index": {"status_code": 200, "text": "<html></html>"},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.details["spec_found"]["/openapi.json"] is False
    assert result.details["spec_found"]["/swagger.json"] is False
    assert result.details["api_found"]["/api/v1"] is False
    assert result.details["api_found"]["/api/v2"] is False


@pytest.mark.asyncio
async def test_api_surface_api_docs_redirect_to_unrelated_path_is_rejected(monkeypatch):
    check = APISurfaceCheck()

    async def _fake_get(self, url, *args, **kwargs):
        responses = {
            "https://example.com/openapi.json": (404, "", "application/json", "https://example.com/openapi.json"),
            "https://example.com/swagger.json": (404, "", "application/json", "https://example.com/swagger.json"),
            "https://example.com/api-docs": (200, "<html>home</html>", "text/html", "https://example.com/de/de"),
            "https://example.com/api/v1": (404, "", "application/json", "https://example.com/api/v1"),
            "https://example.com/api/v2": (404, "", "application/json", "https://example.com/api/v2"),
            "https://example.com/": (200, "<html></html>", "text/html", "https://example.com/"),
        }
        status, text, content_type, final_url = responses[url]
        return type(
            "Resp",
            (),
            {
                "status_code": status,
                "text": text,
                "headers": {"content-type": content_type},
                "url": final_url,
            },
        )()

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 404, "text": "", "url": url})()

    monkeypatch.setattr(httpx.AsyncClient, "get", _fake_get, raising=True)
    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    result = await check.run("https://example.com", {})

    assert result.score == 0.0
    assert result.details["spec_found"]["/api-docs"] is False


@pytest.mark.asyncio
async def test_api_surface_graphql_options_redirect_to_unrelated_path_is_rejected(monkeypatch, fake_get_factory):
    check = APISurfaceCheck()
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory(
            {
                "https://example.com/openapi.json": (404, ""),
                "https://example.com/swagger.json": (404, ""),
                "https://example.com/api-docs": (404, ""),
                "https://example.com/api/v1": (404, ""),
                "https://example.com/api/v2": (404, ""),
            }
        ),
        raising=True,
    )

    async def _fake_options(self, url, *args, **kwargs):
        return type("Resp", (), {"status_code": 204, "text": "", "url": "https://example.com/de/de"})()

    monkeypatch.setattr(httpx.AsyncClient, "options", _fake_options, raising=True)

    result = await check.run("https://example.com", {"index": {"status_code": 200, "text": "<html></html>"}})

    assert result.score == 0.0
    assert result.details["graphql_options_status"] == 204
