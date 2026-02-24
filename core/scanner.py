from __future__ import annotations

import asyncio
from urllib.parse import urljoin

import httpx

from checks.api_surface import APISurfaceCheck
from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from checks.feeds import FeedsCheck
from checks.product_parseability import ProductParseabilityCheck
from checks.robots import RobotsCheck
from checks.seo_meta import SeoMetaCheck
from checks.sitemap import SitemapCheck
from checks.structured_data import StructuredDataCheck
from core.models import ScanResult
from core.scoring import calculate_overall_score, get_grade


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
        ]

    async def scan(self, url: str) -> ScanResult:
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
        targets = [
            ("index", urljoin(url.rstrip("/") + "/", "")),
            ("robots.txt", urljoin(url.rstrip("/") + "/", "robots.txt")),
            ("sitemap.xml", urljoin(url.rstrip("/") + "/", "sitemap.xml")),
            ("llms.txt", urljoin(url.rstrip("/") + "/", "llms.txt")),
            ("llms-full.txt", urljoin(url.rstrip("/") + "/", "llms-full.txt")),
            (".well-known/ai-plugin.json", urljoin(url.rstrip("/") + "/", ".well-known/ai-plugin.json")),
            (".well-known/agent.json", urljoin(url.rstrip("/") + "/", ".well-known/agent.json")),
            (".well-known/mcp.json", urljoin(url.rstrip("/") + "/", ".well-known/mcp.json")),
        ]

        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
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
            response = await client.get(target_url)
        except httpx.HTTPError:
            return {"status_code": None, "text": "", "content_type": None, "final_url": None}
        return {
            "status_code": response.status_code,
            "text": response.text,
            "content_type": response.headers.get("content-type"),
            "final_url": str(response.url),
        }
