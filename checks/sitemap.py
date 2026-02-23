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

        if status_code != 200:
            return CheckResult(
                category="sitemap",
                score=0.0,
                severity=Severity.FAIL,
                signals=[Signal("sitemap_exists", False, Severity.FAIL)],
                details={"status_code": status_code, "robots_sitemap_directive": robots_sitemap_present},
                recommendations=["Publish a sitemap.xml and reference it in robots.txt."],
            )

        valid_xml, urls, has_lastmod, is_fresh = self._inspect_sitemap(sitemap_text)

        if valid_xml and urls > 0 and has_lastmod and is_fresh:
            score = 1.0
            severity = Severity.PASS
        else:
            score = 0.5
            severity = Severity.PARTIAL

        signals = [
            Signal("sitemap_exists", True, Severity.PASS),
            Signal("valid_xml", valid_xml, Severity.PASS if valid_xml else Severity.FAIL),
            Signal("has_urls", urls > 0, Severity.PASS if urls > 0 else Severity.FAIL, detail=f"count={urls}"),
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
                "url_count": urls,
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
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}

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
    def _inspect_sitemap(sitemap_text: str) -> tuple[bool, int, bool, bool]:
        try:
            root = ET.fromstring(sitemap_text)
        except ET.ParseError:
            return False, 0, False, False

        url_nodes = [elem for elem in root.iter() if elem.tag.endswith("url")]
        urls = len(url_nodes)

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

        return True, urls, has_lastmod, is_fresh

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
