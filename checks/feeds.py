from __future__ import annotations

import httpx

from checks.base import BaseCheck
from checks.html_extract import parse_html_features
from core.models import CheckResult, Severity, Signal


class FeedsCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(url)
        if self._is_unreachable_artifact(index):
            return self._inconclusive_result(category="feeds", reason="Homepage HTML unreachable", details={"status_code": index.get("status_code")})

        html = index.get("text", "") if index.get("status_code") == 200 else ""
        parser = parse_html_features(html)

        feed_links = [
            link
            for link in parser.links
            if "alternate" in link.get("rel", "")
            and ("atom+xml" in link.get("type", "") or "rss+xml" in link.get("type", "") or "json" in link.get("type", ""))
        ]
        feed_hrefs = [link.get("href", "") for link in feed_links if link.get("href")]
        structured_feed_hints = [href for href in feed_hrefs if any(token in href.lower() for token in ("product", "catalog", "shop", "merchant", "item"))]

        html_lower = html.lower()
        has_google_shopping_hint = any(
            hint in html_lower for hint in ["google shopping", "merchant center", "shopping feed", "g:price"]
        )

        has_structured_product_feed = bool(structured_feed_hints) or has_google_shopping_hint
        has_generic_feed = len(feed_hrefs) > 0

        if has_structured_product_feed:
            score = 1.0
            severity = Severity.PASS
        elif has_generic_feed:
            score = 0.5
            severity = Severity.PARTIAL
        else:
            score = 0.0
            severity = Severity.FAIL

        signals: list[Signal] = []
        signals.append(
            Signal(
                name="html:alternate_feed_links",
                value=len(feed_hrefs),
                severity=Severity.PASS if feed_hrefs else Severity.FAIL,
            )
        )
        signals.append(
            Signal(
                name="html:structured_feed_hints",
                value=len(structured_feed_hints),
                severity=Severity.PASS if structured_feed_hints else Severity.INCONCLUSIVE,
            )
        )
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
                "alternate_feed_hrefs": feed_hrefs,
                "structured_feed_hrefs": structured_feed_hints,
                "google_shopping_hint": has_google_shopping_hint,
            },
            recommendations=["Expose feed URLs with <link rel='alternate'> metadata and use product-oriented feed naming where possible."]
            if score < 1.0
            else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(url.rstrip("/") + "/")
            except httpx.HTTPError:
                return {"status_code": None, "text": "", "content_type": None, "final_url": None}
        return {
            "status_code": response.status_code,
            "text": response.text,
            "content_type": response.headers.get("content-type"),
            "final_url": str(response.url),
        }
