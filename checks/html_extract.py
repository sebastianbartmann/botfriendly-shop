from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any


class HTMLFeatureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.json_ld_blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.anchors: list[str] = []
        self.h1_count = 0
        self.price_element_count = 0

        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower == "script":
            script_type = attr_map.get("type", "").lower().split(";", 1)[0].strip()
            if script_type == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_parts = []

        if tag_lower == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            content = attr_map.get("content", "")
            if key and content and key not in self.meta:
                self.meta[key] = content

        if tag_lower == "link":
            rel = attr_map.get("rel", "").lower()
            link_type = attr_map.get("type", "").lower()
            href = attr_map.get("href", "")
            if href:
                self.links.append({"rel": rel, "type": link_type, "href": href})

        if tag_lower == "a":
            href = attr_map.get("href", "")
            if href:
                self.anchors.append(href)

        if tag_lower == "h1":
            self.h1_count += 1

        class_id = " ".join([attr_map.get("class", ""), attr_map.get("id", ""), attr_map.get("itemprop", "")]).lower()
        if "price" in class_id:
            self.price_element_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_json_ld:
            block = "".join(self._json_ld_parts).strip()
            if block:
                self.json_ld_blocks.append(block)
            self._in_json_ld = False
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)


def parse_html_features(html: str) -> HTMLFeatureParser:
    parser = HTMLFeatureParser()
    parser.feed(html if isinstance(html, str) else "")
    return parser


def parse_json_ld_blocks(blocks: list[str]) -> tuple[list[Any], int]:
    parsed: list[Any] = []
    malformed = 0
    for raw in blocks:
        text = raw.strip()
        if not text:
            continue
        try:
            parsed.append(json.loads(text))
        except json.JSONDecodeError:
            malformed += 1
    return parsed, malformed


def flatten_json_nodes(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            found.append(value)
            if "@graph" in value:
                _walk(value["@graph"])
            for item in value.values():
                if isinstance(item, (dict, list)):
                    _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(node)
    return found


def normalize_schema_type(raw_type: str) -> str:
    value = raw_type.strip()
    if not value:
        return ""

    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    if ":" in value:
        value = value.rsplit(":", 1)[-1]

    return value.strip()


def extract_schema_types(nodes: list[dict[str, Any]]) -> set[str]:
    types: set[str] = set()
    for node in nodes:
        value = node.get("@type")
        if isinstance(value, str):
            normalized = normalize_schema_type(value)
            if normalized:
                types.add(normalized)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    normalized = normalize_schema_type(item)
                    if normalized:
                        types.add(normalized)
    return types


def parse_price(raw: str | None) -> float | None:
    if not raw or not isinstance(raw, str):
        return None
    compact = raw.replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", compact)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None
