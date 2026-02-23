from __future__ import annotations

from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from checks.html_extract import extract_schema_types, flatten_json_nodes, parse_html_features, parse_json_ld_blocks
from core.models import CheckResult, Severity, Signal

SCHEMA_TYPES = ["Product", "Offer", "AggregateRating", "Organization", "WebSite", "BreadcrumbList"]
OG_TAGS = ["og:title", "og:type", "og:image", "og:price:amount", "og:price:currency", "product:price:amount"]


class StructuredDataCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        index = artifacts.get("index")
        if index is None:
            index = await self._fetch(url)

        status_code = index.get("status_code")
        html = index.get("text", "") if status_code == 200 else ""
        parser = parse_html_features(html)

        parsed_json_ld, malformed_blocks = parse_json_ld_blocks(parser.json_ld_blocks)
        schema_types = set()
        for block in parsed_json_ld:
            schema_types.update(extract_schema_types(flatten_json_nodes(block)))

        found_og_tags = [tag for tag in OG_TAGS if tag in parser.meta]
        has_product_types = "Product" in schema_types or "Offer" in schema_types

        if has_product_types:
            score = 1.0
            severity = Severity.PASS
        elif schema_types:
            score = 0.75
            severity = Severity.PARTIAL
        elif found_og_tags:
            score = 0.5
            severity = Severity.PARTIAL
        else:
            score = 0.0
            severity = Severity.FAIL

        signals: list[Signal] = []
        for schema_type in SCHEMA_TYPES:
            if schema_type in schema_types:
                signals.append(Signal(name=f"schema:{schema_type}", value=True, severity=Severity.PASS))
        for tag in found_og_tags:
            signals.append(Signal(name=f"meta:{tag}", value=True, severity=Severity.PASS))
        if malformed_blocks:
            signals.append(Signal(name="json_ld_malformed_blocks", value=malformed_blocks, severity=Severity.PARTIAL))

        return CheckResult(
            category="structured_data",
            score=score,
            severity=severity,
            signals=signals,
            details={
                "status_code": status_code,
                "json_ld_block_count": len(parser.json_ld_blocks),
                "schema_types": sorted(schema_types),
                "open_graph_tags": sorted(found_og_tags),
                "malformed_json_ld_blocks": malformed_blocks,
            },
            recommendations=["Add valid Product/Offer schema.org JSON-LD and core OpenGraph metadata."] if score < 1.0 else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(urljoin(url.rstrip("/") + "/", ""))
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}
