from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import httpx

from checks.base import BaseCheck
from core.models import CheckResult, Severity, Signal


class SitemapCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        sitemap = artifacts.get("sitemap.xml")
        robots = artifacts.get("robots.txt")

        if sitemap is None:
            sitemap = await self._fetch(urljoin(url.rstrip("/") + "/", "sitemap.xml"))
        if robots is None:
            robots = await self._fetch(urljoin(url.rstrip("/") + "/", "robots.txt"))

        robots_sitemap_present = self._has_robots_sitemap(robots.get("text", "") if robots else "")
        status_code = sitemap.get("status_code")
        sitemap_text = sitemap.get("text", "")
        content_type = sitemap.get("content_type")
        final_url = sitemap.get("final_url")
        is_html_response = isinstance(content_type, str) and "text/html" in content_type.lower()

        if self._is_unreachable_artifact(sitemap):
            return self._inconclusive_result(
                category="sitemap",
                reason="sitemap.xml unreachable",
                details={
                    "status_code": status_code,
                    "content_type": content_type,
                    "final_url": final_url,
                    "robots_sitemap_directive": robots_sitemap_present,
                },
            )

        if status_code != 200 or is_html_response:
            return CheckResult(
                category="sitemap",
                score=0.0,
                severity=Severity.FAIL,
                signals=[Signal("sitemap_exists", False, Severity.FAIL)],
                details={
                    "status_code": status_code,
                    "content_type": content_type,
                    "final_url": final_url,
                    "robots_sitemap_directive": robots_sitemap_present,
                },
                recommendations=["Publish a sitemap.xml and reference it in robots.txt."],
            )

        valid_xml, url_count, sitemap_count, has_lastmod, is_fresh = self._inspect_sitemap(sitemap_text)
        entry_count = sitemap_count if sitemap_count > 0 else url_count
        entry_detail = (
            f"sitemap index with {sitemap_count} child sitemaps"
            if sitemap_count > 0
            else f"sitemap with {url_count} URLs"
        )

        if valid_xml and entry_count > 0 and has_lastmod and is_fresh:
            score = 1.0
            severity = Severity.PASS
        else:
            score = 0.5
            severity = Severity.PARTIAL

        signals = [
            Signal("sitemap_exists", True, Severity.PASS),
            Signal("valid_xml", valid_xml, Severity.PASS if valid_xml else Severity.FAIL),
            Signal(
                "has_urls",
                entry_count > 0,
                Severity.PASS if entry_count > 0 else Severity.FAIL,
                detail=entry_detail,
            ),
            Signal("has_lastmod", has_lastmod, Severity.PASS if has_lastmod else Severity.FAIL),
            Signal("fresh_lastmod", is_fresh, Severity.PASS if is_fresh else Severity.PARTIAL),
            Signal("robots_sitemap_directive", robots_sitemap_present, Severity.PASS if robots_sitemap_present else Severity.PARTIAL),
        ]

        return CheckResult(
            category="sitemap",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "content_type": content_type,
                "final_url": final_url,
                "url_count": url_count,
                "sitemap_count": sitemap_count,
                "has_lastmod": has_lastmod,
                "fresh_lastmod": is_fresh,
                "robots_sitemap_directive": robots_sitemap_present,
            },
            recommendations=["Keep sitemap updated with recent lastmod values."] if score < 1.0 else [],
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

    @staticmethod
    def _has_robots_sitemap(robots_text: str) -> bool:
        for raw_line in robots_text.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, _ = [part.strip() for part in line.split(":", 1)]
            if key.lower() == "sitemap":
                return True
        return False

    @staticmethod
    def _inspect_sitemap(sitemap_text: str) -> tuple[bool, int, int, bool, bool]:
        try:
            root = ET.fromstring(sitemap_text)
        except ET.ParseError:
            return False, 0, 0, False, False

        url_nodes = [elem for elem in root.iter() if elem.tag.endswith("url")]
        sitemap_nodes = [elem for elem in root.iter() if elem.tag.endswith("sitemap")]
        url_count = len(url_nodes)
        sitemap_count = len(sitemap_nodes)

        lastmods: list[datetime] = []
        for elem in root.iter():
            if elem.tag.endswith("lastmod") and elem.text:
                parsed = SitemapCheck._parse_lastmod(elem.text.strip())
                if parsed:
                    lastmods.append(parsed)

        has_lastmod = len(lastmods) > 0
        is_fresh = False
        if has_lastmod:
            newest = max(lastmods)
            age_days = (datetime.now(timezone.utc) - newest).days
            is_fresh = age_days <= 30

        return True, url_count, sitemap_count, has_lastmod, is_fresh

    @staticmethod
    def _parse_lastmod(raw: str) -> datetime | None:
        candidates = [raw]
        if raw.endswith("Z"):
            candidates.append(raw.replace("Z", "+00:00"))
        for candidate in candidates:
            try:
                dt = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return None
