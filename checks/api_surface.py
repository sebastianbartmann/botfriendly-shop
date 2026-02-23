from __future__ import annotations

from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import parse_html_features
from core.models import CheckResult, Severity, Signal

SPEC_PATHS = ["/openapi.json", "/swagger.json", "/api-docs"]
API_PATHS = ["/api/v1", "/api/v2"]
GRAPHQL_PATH = "/graphql"


class APISurfaceCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        spec_found: dict[str, bool] = {}
        api_found: dict[str, bool] = {}
        signals: list[Signal] = []

        for path in SPEC_PATHS:
            key = path.lstrip("/")
            response_data = artifacts.get(key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", key))
            exists = response_data.get("status_code") == 200
            spec_found[path] = exists
            signals.append(Signal(name=f"spec:{path}", value=exists, severity=Severity.PASS if exists else Severity.FAIL))

        for path in API_PATHS:
            key = path.lstrip("/")
            response_data = artifacts.get(key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", key))
            exists = response_data.get("status_code") == 200
            api_found[path] = exists
            signals.append(Signal(name=f"endpoint:{path}", value=exists, severity=Severity.PASS if exists else Severity.INCONCLUSIVE))

        graphql = await self._fetch_options(urljoin(url.rstrip("/") + "/", GRAPHQL_PATH.lstrip("/")))
        graphql_enabled = graphql.get("status_code") in {200, 204, 400, 405}
        signals.append(Signal(name="endpoint:/graphql_options", value=graphql_enabled, severity=Severity.PASS if graphql_enabled else Severity.INCONCLUSIVE))

        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(urljoin(url.rstrip("/") + "/", ""))

        html = index.get("text", "") if index.get("status_code") == 200 else ""
        parser = parse_html_features(html)
        doc_links = [href for href in parser.anchors if any(token in href.lower() for token in ["api", "developer", "docs"])]

        if doc_links:
            signals.append(Signal(name="html:api_doc_links", value=len(doc_links), severity=Severity.PASS))

        has_spec = any(spec_found.values())
        has_docs_or_api_surface = bool(doc_links or graphql_enabled or any(api_found.values()))

        if has_spec:
            score = 1.0
            severity = Severity.PASS
        elif has_docs_or_api_surface:
            score = 0.5
            severity = Severity.PARTIAL
        else:
            score = 0.0
            severity = Severity.FAIL

        return CheckResult(
            category="api_surface",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "spec_found": spec_found,
                "api_found": api_found,
                "graphql_options_status": graphql.get("status_code"),
                "doc_links": doc_links,
            },
            recommendations=["Publish OpenAPI/Swagger specs and link API docs prominently."] if score < 1.0 else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}

    async def _fetch_options(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.options(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}
