from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import httpx

from checks.api_surface import APISurfaceCheck
from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from checks.feeds import FeedsCheck
from checks.product_parseability import ProductParseabilityCheck
from checks.robots import RobotsCheck
from checks.semantic_accessibility import SemanticAccessibilityCheck
from checks.seo_meta import SeoMetaCheck
from checks.sitemap import SitemapCheck
from checks.structured_data import StructuredDataCheck
from core.models import ScanResult
from core.scoring import calculate_overall_score, get_grade
from core.url_validator import validate_url

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
HTTP_TIMEOUT = httpx.Timeout(timeout=30.0, connect=10.0, read=15.0)


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
            SemanticAccessibilityCheck(),
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

        async with httpx.AsyncClient(follow_redirects=True, timeout=HTTP_TIMEOUT) as client:
            tasks = [self._fetch(client, target_url) for _, target_url in targets]
            responses = await asyncio.gather(*tasks)

        artifacts = {artifact_key: response for (artifact_key, _), response in zip(targets, responses)}
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
