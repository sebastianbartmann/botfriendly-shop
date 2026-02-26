from __future__ import annotations

import asyncio
from urllib.parse import urljoin, urlparse

import httpx

from checks.api_surface import APISurfaceCheck
from checks.accessibility import AccessibilityCheck
from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from checks.feeds import FeedsCheck
from checks.product_parseability import ProductParseabilityCheck
from checks.robots import RobotsCheck
from checks.semantic_html import SemanticHtmlCheck
from checks.seo_meta import SeoMetaCheck
from checks.sitemap import SitemapCheck
from checks.structured_data import StructuredDataCheck
from core.models import ScanResult
from core.scoring import calculate_overall_score, get_grade
from core.url_validator import validate_url

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
HTTP_TIMEOUT = httpx.Timeout(timeout=30.0, connect=10.0, read=15.0)
INCONCLUSIVE_HTTP_STATUSES = {401, 403, 408, 425, 429, 451, 500, 502, 503, 504}
DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36 botfriendly-scan/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}


class Scanner:
    def __init__(self, checks=None):
        self.checks = checks if checks is not None else [
            RobotsCheck(),
            DiscoveryCheck(),
            SitemapCheck(),
            StructuredDataCheck(),
            SeoMetaCheck(),
            FeedsCheck(),
            APISurfaceCheck(),
            ProductParseabilityCheck(),
            SemanticHtmlCheck(),
            AccessibilityCheck(),
        ]

    async def scan(self, url: str) -> ScanResult:
        is_valid, error_message = validate_url(url)
        if not is_valid:
            raise ValueError(error_message or "Invalid URL")

        artifacts = await self._http_pass(url)
        results = []
        for check in self.checks:
            results.append(await check.run(url, artifacts))

        overall_score = calculate_overall_score(results)
        grade = get_grade(overall_score)

        return ScanResult(
            url=url,
            overall_score=overall_score,
            check_results=results,
            metadata={"check_count": len(results), "grade": grade},
        )

    async def _http_pass(self, url: str) -> dict:
        is_valid, error_message = validate_url(url)
        if not is_valid:
            raise ValueError(error_message or "Invalid URL")

        targets = [
            ("index", urljoin(url.rstrip("/") + "/", "")),
            ("robots.txt", urljoin(url.rstrip("/") + "/", "robots.txt")),
            ("sitemap.xml", urljoin(url.rstrip("/") + "/", "sitemap.xml")),
            ("llms.txt", urljoin(url.rstrip("/") + "/", "llms.txt")),
            ("llms-full.txt", urljoin(url.rstrip("/") + "/", "llms-full.txt")),
            (".well-known/mcp.json", urljoin(url.rstrip("/") + "/", ".well-known/mcp.json")),
        ]

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=HTTP_TIMEOUT,
            headers=DEFAULT_HTTP_HEADERS,
        ) as client:
            tasks = [self._fetch(client, target_url) for _, target_url in targets]
            responses = await asyncio.gather(*tasks)

        artifacts = {artifact_key: response for (artifact_key, _), response in zip(targets, responses)}
        index_artifact = artifacts.get("index")
        if self._is_unreachable(index_artifact):
            fallback_base = self._alternate_base_url(url)
            if fallback_base:
                fallback_targets = [
                    ("index", urljoin(fallback_base.rstrip("/") + "/", "")),
                    ("robots.txt", urljoin(fallback_base.rstrip("/") + "/", "robots.txt")),
                    ("sitemap.xml", urljoin(fallback_base.rstrip("/") + "/", "sitemap.xml")),
                    ("llms.txt", urljoin(fallback_base.rstrip("/") + "/", "llms.txt")),
                    ("llms-full.txt", urljoin(fallback_base.rstrip("/") + "/", "llms-full.txt")),
                    (".well-known/mcp.json", urljoin(fallback_base.rstrip("/") + "/", ".well-known/mcp.json")),
                ]
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=HTTP_TIMEOUT,
                    headers=DEFAULT_HTTP_HEADERS,
                ) as client:
                    fallback_responses = await asyncio.gather(*[self._fetch(client, target_url) for _, target_url in fallback_targets])
                fallback_artifacts = {
                    artifact_key: response for (artifact_key, _), response in zip(fallback_targets, fallback_responses)
                }
                for key, fallback_artifact in fallback_artifacts.items():
                    if self._is_unreachable(artifacts.get(key)) and not self._is_unreachable(fallback_artifact):
                        artifacts[key] = fallback_artifact

        for discovery_path in DISCOVERY_PATHS:
            artifacts.setdefault(
                discovery_path.lstrip("/"),
                artifacts.get(
                    discovery_path.lstrip("/"),
                    {"status_code": None, "text": "", "content_type": None, "final_url": None},
                ),
            )
        return artifacts

    @staticmethod
    async def _fetch(client: httpx.AsyncClient, target_url: str) -> dict:
        try:
            async with client.stream("GET", target_url) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE_BYTES:
                        break
                text = bytes(content[:MAX_RESPONSE_BYTES]).decode(response.encoding or "utf-8", errors="replace")
        except httpx.HTTPError:
            return {"status_code": None, "text": "", "content_type": None, "final_url": None}
        return {
            "status_code": response.status_code,
            "text": text,
            "content_type": response.headers.get("content-type"),
            "final_url": str(response.url),
        }

    @staticmethod
    def _is_unreachable(artifact: dict | None) -> bool:
        if not isinstance(artifact, dict):
            return True
        status = artifact.get("status_code")
        if not isinstance(status, int):
            return True
        return status in INCONCLUSIVE_HTTP_STATUSES

    @staticmethod
    def _alternate_base_url(url: str) -> str | None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip()
        if not host:
            return None

        alt_host = host[4:] if host.startswith("www.") else f"www.{host}"
        if not alt_host:
            return None

        scheme = parsed.scheme or "https"
        if parsed.port:
            return f"{scheme}://{alt_host}:{parsed.port}"
        return f"{scheme}://{alt_host}"
