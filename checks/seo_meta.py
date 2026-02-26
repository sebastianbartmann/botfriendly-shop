from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import parse_html_features
from core.models import CheckResult, Severity, Signal


class SeoMetaCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(url)

        status_code = index.get("status_code")
        if self._is_unreachable_artifact(index):
            return self._inconclusive_result(
                category="seo_meta",
                reason="Homepage HTML unreachable",
                details={"status_code": status_code},
            )
        html = index.get("text", "") if status_code == 200 else ""
        parser = parse_html_features(html)

        title = self._extract_title(html)
        description = parser.meta.get("description", "").strip()
        canonical = self._extract_canonical(parser.links)
        language = self._extract_html_lang(html)
        viewport = parser.meta.get("viewport", "").strip()
        h1_count = parser.h1_count

        title_score = self._length_scored_value(title, min_len=10, max_len=70)
        description_score = self._length_scored_value(description, min_len=50, max_len=160)
        canonical_score = 1.0 if canonical else 0.0
        language_score = 1.0 if language else 0.0
        viewport_score = 1.0 if viewport else 0.0
        if h1_count == 1:
            h1_score = 1.0
        elif h1_count > 1:
            h1_score = 0.5
        else:
            h1_score = 0.0

        item_scores = [title_score, description_score, canonical_score, language_score, viewport_score, h1_score]
        score = sum(item_scores) / len(item_scores)
        epsilon = 1e-9
        if score >= 0.8 - epsilon:
            severity = Severity.PASS
        elif score >= 0.4 - epsilon:
            severity = Severity.PARTIAL
        else:
            severity = Severity.FAIL

        signals = [
            Signal(name="title", value=title or "missing", severity=self._severity_for_score(title_score)),
            Signal(name="description", value=description or "missing", severity=self._severity_for_score(description_score)),
            Signal(name="canonical", value=canonical or "missing", severity=self._severity_for_score(canonical_score)),
            Signal(name="language", value=language or "missing", severity=self._severity_for_score(language_score)),
            Signal(name="viewport", value=viewport or "missing", severity=self._severity_for_score(viewport_score)),
            Signal(name="h1", value=h1_count if h1_count > 0 else "missing", severity=self._severity_for_score(h1_score)),
        ]

        recommendations: list[str] = []
        if not title:
            recommendations.append("Add a non-empty <title> tag (ideal length: 10-70 characters).")
        elif title_score < 1.0:
            recommendations.append("Adjust the <title> length to 10-70 characters.")

        if not description:
            recommendations.append("Add a non-empty meta description (ideal length: 50-160 characters).")
        elif description_score < 1.0:
            recommendations.append("Adjust the meta description length to 50-160 characters.")

        if not canonical:
            recommendations.append("Add a canonical URL tag (<link rel='canonical' href='...'>).")

        if not language:
            recommendations.append("Set the document language using the <html lang='...'> attribute.")

        if not viewport:
            recommendations.append("Add a viewport meta tag for mobile rendering support.")

        if h1_count == 0:
            recommendations.append("Add an <h1> heading to the page.")
        elif h1_count > 1:
            recommendations.append("Use exactly one <h1> heading to improve heading hierarchy.")

        return CheckResult(
            category="seo_meta",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "title_length": len(title),
                "description_length": len(description),
                "canonical": canonical,
                "language": language,
                "viewport": viewport,
                "h1_count": h1_count,
            },
            recommendations=recommendations,
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(urljoin(url.rstrip("/") + "/", ""))
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}

    @staticmethod
    def _severity_for_score(item_score: float) -> Severity:
        if item_score >= 1.0:
            return Severity.PASS
        if item_score > 0.0:
            return Severity.PARTIAL
        return Severity.FAIL

    @staticmethod
    def _length_scored_value(value: str, min_len: int, max_len: int) -> float:
        if not value:
            return 0.0
        if min_len <= len(value) <= max_len:
            return 1.0
        return 0.5

    @staticmethod
    def _extract_title(html: str) -> str:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return " ".join(match.group(1).split()).strip()

    @staticmethod
    def _extract_html_lang(html: str) -> str:
        quoted_match = re.search(
            r"<html\b[^>]*\blang\s*=\s*(['\"])\s*(.*?)\s*\1",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if quoted_match:
            return quoted_match.group(2).strip()

        unquoted_match = re.search(r"<html\b[^>]*\blang\s*=\s*([^\s>]+)", html, flags=re.IGNORECASE)
        if unquoted_match:
            return unquoted_match.group(1).strip()
        return ""

    @staticmethod
    def _extract_canonical(links: list[dict[str, str]]) -> str:
        for link in links:
            rel_tokens = {token.strip() for token in link.get("rel", "").lower().split() if token.strip()}
            if "canonical" in rel_tokens:
                href = link.get("href", "").strip()
                if href:
                    return href
        return ""
