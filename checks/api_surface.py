from __future__ import annotations

from urllib.parse import urljoin, urlparse

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
        probe_status: dict[str, str] = {}
        signals: list[Signal] = []
        unreachable_probes = 0

        for path in SPEC_PATHS:
            key = path.lstrip("/")
            response_data = artifacts.get(key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", key))
            unreachable = self._is_unreachable_artifact(response_data)
            content_type = response_data.get("content_type")
            is_html_response = isinstance(content_type, str) and "text/html" in content_type.lower()
            should_check_content_type = path in {"/openapi.json", "/swagger.json"}
            is_docs_redirect_valid = True
            if path == "/api-docs" and response_data.get("status_code") == 200:
                is_docs_redirect_valid = self._path_contains_any(response_data.get("final_url"), {"api-docs", "api", "docs"})
            exists = (
                response_data.get("status_code") == 200
                and not unreachable
                and not (should_check_content_type and is_html_response)
                and is_docs_redirect_valid
            )
            spec_found[path] = exists
            probe_status[f"spec:{path}"] = "found" if exists else "unknown" if unreachable else "not_found"
            if unreachable:
                unreachable_probes += 1
            signals.append(
                Signal(
                    name=f"spec:{path}",
                    value=exists if not unreachable else "unknown",
                    severity=Severity.PASS if exists else Severity.INCONCLUSIVE if unreachable else Severity.FAIL,
                )
            )

        for path in API_PATHS:
            key = path.lstrip("/")
            response_data = artifacts.get(key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", key))
            unreachable = self._is_unreachable_artifact(response_data)
            content_type = response_data.get("content_type")
            is_html_response = isinstance(content_type, str) and "text/html" in content_type.lower()
            exists = response_data.get("status_code") == 200 and not is_html_response and not unreachable
            api_found[path] = exists
            probe_status[f"endpoint:{path}"] = "found" if exists else "unknown" if unreachable else "not_found"
            if unreachable:
                unreachable_probes += 1
            signals.append(
                Signal(
                    name=f"endpoint:{path}",
                    value=exists if not unreachable else "unknown",
                    severity=Severity.PASS if exists else Severity.INCONCLUSIVE,
                )
            )

        graphql = await self._fetch_options(urljoin(url.rstrip("/") + "/", GRAPHQL_PATH.lstrip("/")))
        graphql_unreachable = self._is_unreachable_artifact(graphql)
        graphql_enabled = (not graphql_unreachable) and graphql.get("status_code") in {200, 204, 400, 405} and self._path_contains_any(
            graphql.get("final_url"), {"graphql"}
        )
        probe_status["endpoint:/graphql_options"] = "found" if graphql_enabled else "unknown" if graphql_unreachable else "not_found"
        if graphql_unreachable:
            unreachable_probes += 1
        signals.append(
            Signal(
                name="endpoint:/graphql_options",
                value=graphql_enabled if not graphql_unreachable else "unknown",
                severity=Severity.PASS if graphql_enabled else Severity.INCONCLUSIVE,
            )
        )

        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(urljoin(url.rstrip("/") + "/", ""))
        index_unreachable = self._is_unreachable_artifact(index)

        total_probes = len(SPEC_PATHS) + len(API_PATHS) + 1
        if index_unreachable and unreachable_probes == total_probes:
            return self._inconclusive_result(
                category="api_surface",
                reason="API probes and homepage HTML were unreachable",
                details={
                    "spec_found": spec_found,
                    "api_found": api_found,
                    "probe_status": probe_status,
                    "graphql_options_status": graphql.get("status_code"),
                },
            )

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
                "probe_status": probe_status,
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
                return {"status_code": None, "text": "", "content_type": None, "final_url": None}
        return {
            "status_code": response.status_code,
            "text": response.text,
            "content_type": response.headers.get("content-type"),
            "final_url": str(response.url),
        }

    async def _fetch_options(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.options(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": "", "final_url": None}
        response_url = getattr(response, "url", url)
        return {"status_code": response.status_code, "text": response.text, "final_url": str(response_url)}

    @staticmethod
    def _path_contains_any(final_url: str | None, tokens: set[str]) -> bool:
        if not final_url:
            return False
        path = urlparse(final_url).path.lower()
        return any(token in path for token in tokens)
