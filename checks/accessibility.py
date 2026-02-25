from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
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


class AccessibilityCheck(BaseCheck):
    requires_browser = False

    _BAD_LINK_TEXT = {
        "click here",
        "read more",
        "link",
        "here",
        "more",
        "learn more",
    }

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(url)

        status_code = index.get("status_code")
        html = index.get("text", "") if status_code == 200 else ""

        html_text = html if isinstance(html, str) else ""
        soup = _parse_html(html_text)

        image_alt_score, image_alt_details = self._check_image_alt_text(soup)
        landmarks_score, landmarks_details = self._check_landmarks(soup)
        form_labels_score, form_labels_details = self._check_form_labels(soup)
        link_quality_score, link_quality_details = self._check_link_quality(soup)
        skip_nav_score, skip_nav_details = self._check_skip_navigation(soup)
        table_accessibility_score, table_accessibility_details = self._check_table_accessibility(soup)

        item_scores = [
            image_alt_score,
            landmarks_score,
            form_labels_score,
            link_quality_score,
            skip_nav_score,
            table_accessibility_score,
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
                name="image_alt_text",
                value=f"{image_alt_details['with_alt']}/{image_alt_details['total_images']}",
                severity=self._severity_for_score(image_alt_score),
            ),
            Signal(
                name="landmarks",
                value=f"{landmarks_details['present_count']}/4",
                severity=self._severity_for_score(landmarks_score),
            ),
            Signal(
                name="form_labels",
                value=f"{form_labels_details['labeled_inputs']}/{form_labels_details['total_inputs']}",
                severity=self._severity_for_score(form_labels_score),
            ),
            Signal(
                name="link_quality",
                value=f"{link_quality_details['descriptive_links']}/{link_quality_details['total_links']}",
                severity=self._severity_for_score(link_quality_score),
            ),
            Signal(
                name="skip_navigation",
                value=skip_nav_details["summary"],
                severity=self._severity_for_score(skip_nav_score),
            ),
            Signal(
                name="table_accessibility",
                value=table_accessibility_details["summary"],
                severity=self._severity_for_score(table_accessibility_score),
            ),
        ]

        recommendations: list[str] = []
        if image_alt_score < 1.0:
            recommendations.append("Add meaningful, non-empty alt text to all non-decorative images.")
        if landmarks_score < 1.0:
            recommendations.append("Provide core page landmarks (banner, navigation, main, contentinfo) with semantic tags or ARIA roles.")
        if form_labels_score < 1.0:
            recommendations.append("Associate each form input with a visible <label>, aria-label, or aria-labelledby.")
        if link_quality_score < 1.0:
            recommendations.append("Use descriptive link text instead of generic phrases like 'click here' or 'read more'.")
        if skip_nav_score < 1.0:
            recommendations.append("Add a skip-to-content link near the top of the page for keyboard and assistive tech users.")
        if table_accessibility_score < 1.0:
            recommendations.append("For data tables, use <thead>, header cells (<th>), and scope attributes.")

        return CheckResult(
            category="accessibility",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "image_alt_text": image_alt_details,
                "landmarks": landmarks_details,
                "form_labels": form_labels_details,
                "link_quality": link_quality_details,
                "skip_navigation": skip_nav_details,
                "table_accessibility": table_accessibility_details,
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
    def _check_image_alt_text(soup) -> tuple[float, dict]:
        images = soup.find_all("img")
        total_images = len(images)
        if total_images == 0:
            return 0.5, {"total_images": 0, "with_alt": 0, "ratio": 1.0}

        with_alt = 0
        for image in images:
            alt_text = image.get("alt")
            if isinstance(alt_text, str) and alt_text.strip():
                with_alt += 1

        ratio = with_alt / total_images
        return ratio, {"total_images": total_images, "with_alt": with_alt, "ratio": ratio}

    @staticmethod
    def _check_landmarks(soup) -> tuple[float, dict]:
        landmarks = {
            "banner": bool(soup.find("header") or soup.find(attrs={"role": re.compile(r"\bbanner\b", flags=re.IGNORECASE)})),
            "navigation": bool(soup.find("nav") or soup.find(attrs={"role": re.compile(r"\bnavigation\b", flags=re.IGNORECASE)})),
            "main": bool(soup.find("main") or soup.find(attrs={"role": re.compile(r"\bmain\b", flags=re.IGNORECASE)})),
            "contentinfo": bool(soup.find("footer") or soup.find(attrs={"role": re.compile(r"\bcontentinfo\b", flags=re.IGNORECASE)})),
        }
        present_count = sum(1 for present in landmarks.values() if present)
        score = present_count / len(landmarks)
        return score, {"present": landmarks, "present_count": present_count}

    @staticmethod
    def _check_form_labels(soup) -> tuple[float, dict]:
        inputs = [tag for tag in soup.find_all("input") if (tag.get("type") or "text").lower() not in {"hidden", "submit", "button", "reset", "image"}]

        total_inputs = len(inputs)
        if total_inputs == 0:
            return 0.5, {"total_inputs": 0, "labeled_inputs": 0, "ratio": 1.0}

        labels_for = {
            value.strip()
            for label in soup.find_all("label")
            for value in [label.get("for")]
            if isinstance(value, str) and value.strip()
        }

        labeled_inputs = 0
        for input_tag in inputs:
            aria_label = (input_tag.get("aria-label") or "").strip()
            aria_labelledby = (input_tag.get("aria-labelledby") or "").strip()
            input_id = (input_tag.get("id") or "").strip()
            wrapped_by_label = input_tag.find_parent("label") is not None

            if aria_label or aria_labelledby or wrapped_by_label or (input_id and input_id in labels_for):
                labeled_inputs += 1

        ratio = labeled_inputs / total_inputs
        return ratio, {"total_inputs": total_inputs, "labeled_inputs": labeled_inputs, "ratio": ratio}

    def _check_link_quality(self, soup) -> tuple[float, dict]:
        links = [tag for tag in soup.find_all("a") if tag.get("href")]
        total_links = len(links)
        if total_links == 0:
            return 0.5, {"total_links": 0, "descriptive_links": 0, "ratio": 1.0}

        descriptive_links = 0
        for link in links:
            text = " ".join(link.stripped_strings).strip().lower()
            if not text:
                text = (link.get("aria-label") or "").strip().lower()
            text = re.sub(r"\s+", " ", text)
            if text and text not in self._BAD_LINK_TEXT:
                descriptive_links += 1

        ratio = descriptive_links / total_links
        return ratio, {"total_links": total_links, "descriptive_links": descriptive_links, "ratio": ratio}

    @staticmethod
    def _check_skip_navigation(soup) -> tuple[float, dict]:
        for link in soup.find_all("a"):
            href = (link.get("href") or "").strip().lower()
            text = " ".join(link.stripped_strings).strip().lower()
            if "skip" in text and href.startswith("#"):
                return 1.0, {"present": True, "href": href, "summary": href}

        return 0.0, {"present": False, "href": "", "summary": "missing"}

    @staticmethod
    def _check_table_accessibility(soup) -> tuple[float, dict]:
        tables = soup.find_all("table")
        if not tables:
            return 1.0, {
                "table_count": 0,
                "accessible_tables": 0,
                "average_table_score": 1.0,
                "summary": "no_tables",
            }

        table_scores: list[float] = []
        accessible_tables = 0
        for table in tables:
            has_thead = table.find("thead") is not None
            headers = table.find_all("th")
            has_headers = len(headers) > 0
            has_scope = has_headers and all((header.get("scope") or "").strip() for header in headers)

            component_scores = [1.0 if has_thead else 0.0, 1.0 if has_headers else 0.0, 1.0 if has_scope else 0.0]
            table_score = sum(component_scores) / len(component_scores)
            table_scores.append(table_score)
            if table_score == 1.0:
                accessible_tables += 1

        average_table_score = sum(table_scores) / len(table_scores)
        return average_table_score, {
            "table_count": len(tables),
            "accessible_tables": accessible_tables,
            "average_table_score": average_table_score,
            "summary": f"{accessible_tables}/{len(tables)}",
        }
