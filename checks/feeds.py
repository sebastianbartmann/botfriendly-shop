from __future__ import annotations

from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import parse_html_features
from core.models import CheckResult, Severity, Signal

FEED_PATHS = ["/feed.xml", "/feeds/products.atom", "/products.json", "/feed"]


class FeedsCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        found_paths: dict[str, bool] = {}
        signals: list[Signal] = []

        for path in FEED_PATHS:
            key = path.lstrip("/")
            response_data = artifacts.get(key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", key))

            exists = response_data.get("status_code") == 200
            found_paths[path] = exists
            signals.append(
                Signal(
                    name=f"path:{path}",
                    value="found" if exists else "not_found",
                    severity=Severity.PASS if exists else Severity.FAIL,
                )
            )

        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(urljoin(url.rstrip("/") + "/", ""))

        html = index.get("text", "") if index.get("status_code") == 200 else ""
        parser = parse_html_features(html)

        alternate_feeds = [
            link for link in parser.links if "alternate" in link.get("rel", "") and ("atom+xml" in link.get("type", "") or "rss+xml" in link.get("type", ""))
        ]
        feed_hrefs = [link.get("href", "") for link in alternate_feeds]

        html_lower = html.lower()
        has_google_shopping_hint = any(
            hint in html_lower for hint in ["google shopping", "merchant center", "shopping feed", "g:price"]
        )

        has_structured_product_feed = (
            found_paths.get("/feeds/products.atom", False)
            or found_paths.get("/products.json", False)
            or any("products.atom" in href.lower() or "products.json" in href.lower() for href in feed_hrefs)
            or has_google_shopping_hint
        )

        has_generic_feed = (
            found_paths.get("/feed.xml", False)
            or found_paths.get("/feed", False)
            or len(alternate_feeds) > 0
        )

        if has_structured_product_feed:
            score = 1.0
            severity = Severity.PASS
        elif has_generic_feed:
            score = 0.5
            severity = Severity.PARTIAL
        else:
            score = 0.0
            severity = Severity.FAIL

        if alternate_feeds:
            signals.append(Signal(name="html:alternate_feed_links", value=len(alternate_feeds), severity=Severity.PASS))
        signals.append(
            Signal(
                name="html:google_shopping_hint",
                value=has_google_shopping_hint,
                severity=Severity.PASS if has_google_shopping_hint else Severity.INCONCLUSIVE,
            )
        )

        return CheckResult(
            category="feeds",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "found_paths": found_paths,
                "alternate_feed_hrefs": feed_hrefs,
                "google_shopping_hint": has_google_shopping_hint,
            },
            recommendations=["Expose a structured product feed (for example /products.json or products atom feed)."] if score < 1.0 else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}
