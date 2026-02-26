from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import parse_html_features
from core.models import CheckResult, Severity, Signal

try:
    from bs4 import BeautifulSoup as _BS4BeautifulSoup

    def _parse_html(html: str):
        return _BS4BeautifulSoup(html, "html.parser")

except ModuleNotFoundError:

    class _SimpleNode:
        def __init__(self, name: str, attrs: dict[str, str] | None = None, parent: _SimpleNode | None = None) -> None:
            self.name = name.lower()
            self.attrs = attrs or {}
            self.parent = parent
            self.children: list[_SimpleNode] = []
            self.text_parts: list[str] = []

        def get(self, key: str, default: str = "") -> str:
            return self.attrs.get(key, default)

        def find(self, name=None, attrs: dict | None = None):  # noqa: ANN001
            found = self.find_all(name=name, attrs=attrs)
            return found[0] if found else None

        def find_all(self, name=None, attrs: dict | None = None):  # noqa: ANN001
            matches: list[_SimpleNode] = []
            for node in self._iter_descendants(include_self=False):
                if _matches_name(node.name, name) and _matches_attrs(node.attrs, attrs):
                    matches.append(node)
            return matches

        def find_parent(self, name: str | None = None):
            current = self.parent
            while current is not None:
                if name is None or current.name == name:
                    return current
                current = current.parent
            return None

        @property
        def stripped_strings(self):
            for text in _iter_text(self):
                stripped = " ".join(text.split())
                if stripped:
                    yield stripped

        def _iter_descendants(self, include_self: bool = False):
            if include_self:
                yield self
            for child in self.children:
                yield child
                yield from child._iter_descendants(include_self=False)

    class _SimpleSoup(_SimpleNode):
        @classmethod
        def parse(cls, html: str) -> _SimpleSoup:
            parser = _SimpleHTMLParser()
            parser.feed(html)
            parser.close()
            return parser.root

    class _SimpleHTMLParser(HTMLParser):
        _VOID_TAGS = {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }

        def __init__(self) -> None:
            super().__init__()
            self.root = _SimpleSoup("[document]")
            self._stack: list[_SimpleNode] = [self.root]

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attr_map = {k.lower(): (v or "") for k, v in attrs}
            parent = self._stack[-1]
            node = _SimpleNode(tag, attr_map, parent)
            parent.children.append(node)
            if tag.lower() not in self._VOID_TAGS:
                self._stack.append(node)

        def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.handle_starttag(tag, attrs)

        def handle_endtag(self, tag: str) -> None:
            lowered = tag.lower()
            for idx in range(len(self._stack) - 1, 0, -1):
                if self._stack[idx].name == lowered:
                    del self._stack[idx:]
                    return

        def handle_data(self, data: str) -> None:
            if self._stack:
                self._stack[-1].text_parts.append(data)

    def _iter_text(node: _SimpleNode):
        for part in node.text_parts:
            yield part
        for child in node.children:
            yield from _iter_text(child)

    def _matches_name(tag_name: str, expected) -> bool:  # noqa: ANN001
        if expected is None:
            return True
        if isinstance(expected, str):
            return tag_name == expected
        if isinstance(expected, (list, tuple, set)):
            return tag_name in expected
        if hasattr(expected, "match"):
            return bool(expected.match(tag_name))
        return False

    def _matches_attrs(actual: dict[str, str], expected: dict | None) -> bool:
        if not expected:
            return True
        for key, value in expected.items():
            actual_value = actual.get(key, "")
            if hasattr(value, "search"):
                if not value.search(actual_value):
                    return False
            elif actual_value != str(value):
                return False
        return True

    def _parse_html(html: str):
        return _SimpleSoup.parse(html)


class SemanticHtmlCheck(BaseCheck):
    requires_browser = False

    _SEMANTIC_ELEMENTS = ("header", "nav", "main", "footer", "article", "section", "aside")

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(url)

        status_code = index.get("status_code")
        if self._is_unreachable_artifact(index):
            return self._inconclusive_result(
                category="semantic_html",
                reason="Homepage HTML unreachable",
                details={"status_code": status_code},
            )
        html = index.get("text", "") if status_code == 200 else ""

        html_text = html if isinstance(html, str) else ""
        soup = _parse_html(html_text)
        parser = parse_html_features(html_text)

        semantic_elements_score, semantic_elements_used = self._check_semantic_elements(soup)
        heading_score, heading_details = self._check_heading_hierarchy(soup, parser.h1_count)
        nav_list_score, nav_list_details = self._check_semantic_navigation_lists(soup)
        csr_trap_score, csr_trap_details = self._check_csr_trap(soup, html_text)
        waf_score, waf_details = self._check_waf_interference(status_code, html_text)

        item_scores = [
            semantic_elements_score,
            heading_score,
            nav_list_score,
            csr_trap_score,
            waf_score,
        ]
        score = sum(item_scores) / len(item_scores)
        if not html.strip():
            score = 0.0

        epsilon = 1e-9
        if score >= 0.8 - epsilon:
            severity = Severity.PASS
        elif score >= 0.4 - epsilon:
            severity = Severity.PARTIAL
        else:
            severity = Severity.FAIL

        signals = [
            Signal(
                name="semantic_elements",
                value=f"{len(semantic_elements_used)}/{len(self._SEMANTIC_ELEMENTS)}",
                severity=self._severity_for_score(semantic_elements_score),
            ),
            Signal(
                name="heading_hierarchy",
                value=heading_details["summary"],
                severity=self._severity_for_score(heading_score),
            ),
            Signal(
                name="semantic_navigation_lists",
                value=nav_list_details["summary"],
                severity=self._severity_for_score(nav_list_score),
            ),
            Signal(
                name="csr_trap",
                value=csr_trap_details["summary"],
                severity=self._severity_for_score(csr_trap_score),
            ),
            Signal(
                name="waf_interference",
                value=waf_details["summary"],
                severity=self._severity_for_score(waf_score),
            ),
        ]

        recommendations: list[str] = []
        if semantic_elements_score < 1.0:
            recommendations.append("Use more HTML5 semantic elements like <header>, <main>, <article>, and <footer>.")
        if heading_score < 1.0:
            recommendations.append("Use at least one <h1> and avoid skipped heading levels (e.g., h2 -> h4).")
        if nav_list_score < 1.0:
            recommendations.append("Mark navigation menus with semantic list markup (<ul>/<ol>/<li>) inside navigation landmarks.")
        if csr_trap_score < 1.0:
            recommendations.append("Server-render key storefront content in initial HTML; avoid shipping only a JS app shell.")
        if waf_score < 1.0:
            recommendations.append("Allow non-browser AI fetchers through bot protection for read-only storefront pages.")

        return CheckResult(
            category="semantic_html",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "semantic_elements_used": semantic_elements_used,
                "heading_hierarchy": heading_details,
                "semantic_navigation_lists": nav_list_details,
                "csr_trap": csr_trap_details,
                "waf_interference": waf_details,
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

    def _check_semantic_elements(self, soup) -> tuple[float, list[str]]:
        used = [tag for tag in self._SEMANTIC_ELEMENTS if soup.find(tag) is not None]
        return len(used) / len(self._SEMANTIC_ELEMENTS), used

    @staticmethod
    def _check_heading_hierarchy(soup, h1_count: int) -> tuple[float, dict]:
        levels = [int(tag.name[1]) for tag in soup.find_all(re.compile(r"^h[1-6]$"))]

        skipped_transitions = 0
        for prev, curr in zip(levels, levels[1:]):
            if curr > prev + 1:
                skipped_transitions += 1

        starts_with_h1 = bool(levels) and levels[0] == 1
        no_skips = skipped_transitions == 0
        starts_with_heading = bool(levels)
        starts_with_h2 = starts_with_heading and levels[0] == 2

        if h1_count == 1:
            score = 1.0
            message = "Exactly one <h1> found."
        elif h1_count > 1:
            score = 0.75
            message = "Multiple <h1> elements found; keep one primary heading when possible."
        elif starts_with_h2:
            score = 0.25
            message = "Headings start at <h2> without a primary <h1>."
        else:
            score = 0.0
            message = "No <h1> heading found."

        if not no_skips:
            score = max(score - 0.5, 0.0)

        return score, {
            "h1_count": h1_count,
            "heading_levels": levels,
            "skipped_transitions": skipped_transitions,
            "starts_with_h1": starts_with_h1,
            "starts_with_h2": starts_with_h2,
            "message": message,
            "summary": f"h1={h1_count}, skips={skipped_transitions}",
        }

    @staticmethod
    def _check_semantic_navigation_lists(soup) -> tuple[float, dict]:
        nav_containers = [
            tag
            for tag in soup.find_all(["nav", "header", "div", "aside", "section"])
            if "navigation" in (tag.get("role", "") or "").lower().split()
        ]
        nav_containers.extend(soup.find_all("nav"))

        seen: set[int] = set()
        deduped_nav_containers = []
        for container in nav_containers:
            identity = id(container)
            if identity not in seen:
                deduped_nav_containers.append(container)
                seen.add(identity)

        semantic_nav_count = 0
        for container in deduped_nav_containers:
            for list_tag in container.find_all(["ul", "ol"]):
                if list_tag.find("li") is not None:
                    semantic_nav_count += 1
                    break

        if semantic_nav_count > 0:
            score = 1.0
        elif deduped_nav_containers:
            score = 0.75
        else:
            score = 0.0

        return score, {
            "navigation_regions": len(deduped_nav_containers),
            "semantic_navigation_regions": semantic_nav_count,
            "summary": f"regions={len(deduped_nav_containers)}, semantic={semantic_nav_count}",
        }

    @staticmethod
    def _check_csr_trap(soup, html_text: str) -> tuple[float, dict]:
        root_markers = (
            "id='root'",
            'id="root"',
            "id='app'",
            'id="app"',
            "id='__next'",
            'id="__next"',
            "id='__nuxt'",
            'id="__nuxt"',
        )
        html_lower = html_text.lower()
        has_root_marker = any(marker in html_lower for marker in root_markers)
        scripts = soup.find_all("script")
        script_count = len(scripts)
        text_length = len(" ".join(soup.stripped_strings))
        is_sparse_text = text_length < 200
        script_heavy = script_count >= 5
        likely_csr_shell = has_root_marker and (is_sparse_text or script_heavy)
        summary = f"root={has_root_marker}, scripts={script_count}, text_len={text_length}"
        return (0.0 if likely_csr_shell else 1.0), {
            "likely_csr_shell": likely_csr_shell,
            "has_root_marker": has_root_marker,
            "script_count": script_count,
            "visible_text_length": text_length,
            "summary": summary,
        }

    @staticmethod
    def _check_waf_interference(status_code: int | None, html_text: str) -> tuple[float, dict]:
        html_lower = html_text.lower()
        waf_markers = [
            "just a moment",
            "cf-please-wait",
            "checking your browser",
            "attention required",
            "captcha",
            "datadome",
            "perimeterx",
        ]
        matched = [marker for marker in waf_markers if marker in html_lower]
        blocked = bool(matched) or status_code == 403
        summary = "blocked_or_challenged" if blocked else "not_detected"
        return (0.0 if blocked else 1.0), {
            "blocked_or_challenged": blocked,
            "status_code": status_code,
            "matched_markers": matched,
            "summary": summary,
        }
