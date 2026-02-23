from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import (
    extract_schema_types,
    flatten_json_nodes,
    normalize_schema_type,
    parse_html_features,
    parse_json_ld_blocks,
    parse_price,
)
from core.models import CheckResult, Severity, Signal


class ProductParseabilityCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(urljoin(url.rstrip("/") + "/", ""))

        status_code = index.get("status_code")
        html = index.get("text", "") if status_code == 200 else ""
        parser = parse_html_features(html)

        parsed_json_ld, malformed_blocks = parse_json_ld_blocks(parser.json_ld_blocks)
        nodes: list[dict[str, Any]] = []
        for block in parsed_json_ld:
            nodes.extend(flatten_json_nodes(block))

        schema_types = extract_schema_types(nodes)
        product_node = self._find_product_node(nodes)
        jsonld_name = self._to_text(product_node.get("name")) if product_node else ""
        offer_node = self._find_offer_node(product_node) if product_node else None
        jsonld_price = self._to_text(offer_node.get("price")) if offer_node else ""
        jsonld_availability = self._to_text(offer_node.get("availability")) if offer_node else ""

        og_title = parser.meta.get("og:title", "")
        og_price = parser.meta.get("og:price:amount", parser.meta.get("product:price:amount", ""))
        og_currency = parser.meta.get("og:price:currency", "")

        has_complete_jsonld = bool("Product" in schema_types and jsonld_name and jsonld_price and jsonld_availability)
        has_meta_basics = bool(og_title and og_price and og_currency)
        has_semantic_html = parser.h1_count > 0 and parser.price_element_count > 0

        jsonld_price_num = parse_price(jsonld_price)
        og_price_num = parse_price(og_price)
        price_consistent = True
        if jsonld_price_num is not None and og_price_num is not None:
            price_consistent = abs(jsonld_price_num - og_price_num) < 0.01

        rich_complete = has_complete_jsonld and has_meta_basics and has_semantic_html and price_consistent
        partial_signals = any(
            [
                bool(schema_types),
                bool(jsonld_name or jsonld_price or jsonld_availability),
                bool(og_title or og_price or og_currency),
                parser.h1_count > 0,
                parser.price_element_count > 0,
            ]
        )

        if rich_complete:
            score = 1.0
            severity = Severity.PASS
        elif partial_signals:
            score = 0.5
            severity = Severity.PARTIAL
        else:
            score = 0.0
            severity = Severity.FAIL

        signals = [
            Signal("jsonld_product_type", "Product" in schema_types, Severity.PASS if "Product" in schema_types else Severity.FAIL),
            Signal("jsonld_complete_product", has_complete_jsonld, Severity.PASS if has_complete_jsonld else Severity.PARTIAL),
            Signal("meta_product_basics", has_meta_basics, Severity.PASS if has_meta_basics else Severity.PARTIAL),
            Signal("semantic_h1", parser.h1_count > 0, Severity.PASS if parser.h1_count > 0 else Severity.FAIL),
            Signal("semantic_price_elements", parser.price_element_count > 0, Severity.PASS if parser.price_element_count > 0 else Severity.PARTIAL),
            Signal("price_consistency", price_consistent, Severity.PASS if price_consistent else Severity.FAIL),
        ]
        if malformed_blocks:
            signals.append(Signal("json_ld_malformed_blocks", malformed_blocks, Severity.PARTIAL))

        return CheckResult(
            category="product_parseability",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "schema_types": sorted(schema_types),
                "jsonld_name": jsonld_name,
                "jsonld_price": jsonld_price,
                "jsonld_availability": jsonld_availability,
                "og_title": og_title,
                "og_price": og_price,
                "og_currency": og_currency,
                "h1_count": parser.h1_count,
                "price_element_count": parser.price_element_count,
                "price_consistent": price_consistent,
                "malformed_json_ld_blocks": malformed_blocks,
            },
            recommendations=["Expose complete, consistent Product JSON-LD and matching page metadata."] if score < 1.0 else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}

    @staticmethod
    def _to_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value)

    @staticmethod
    def _find_product_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        for node in nodes:
            raw_type = node.get("@type")
            if isinstance(raw_type, str) and normalize_schema_type(raw_type) == "Product":
                return node
            if isinstance(raw_type, list) and any(isinstance(item, str) and normalize_schema_type(item) == "Product" for item in raw_type):
                return node
        return None

    @staticmethod
    def _find_offer_node(product: dict[str, Any]) -> dict[str, Any] | None:
        offers = product.get("offers")
        if isinstance(offers, dict):
            return offers
        if isinstance(offers, list):
            for item in offers:
                if isinstance(item, dict):
                    return item
        return None
