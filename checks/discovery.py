from __future__ import annotations

from urllib.parse import urlparse
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from core.models import CheckResult, Severity, Signal

DISCOVERY_PATHS = [
    "/llms.txt",
    "/llms-full.txt",
    "/.well-known/mcp.json",
]


class DiscoveryCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        found_count = 0
        signals: list[Signal] = []
        details: dict[str, dict] = {}

        for path in DISCOVERY_PATHS:
            artifact_key = path.lstrip("/")
            response_data = artifacts.get(artifact_key)
            if response_data is None:
                response_data = await self._fetch(urljoin(url.rstrip("/") + "/", path.lstrip("/")))

            status_code = response_data.get("status_code")
            content_type = response_data.get("content_type")
            final_url = response_data.get("final_url")
            content_type_ok = self._is_expected_content_type(path, content_type)
            path_ok = self._is_expected_final_path(path, final_url)
            exists = status_code == 200 and content_type_ok and path_ok
            text = response_data.get("text", "") if exists else ""
            if exists:
                found_count += 1

            preview = text[:120].replace("\n", " ").strip()
            signal_value = "found" if exists else "not_found"
            signals.append(
                Signal(
                    name=path,
                    value=signal_value,
                    severity=Severity.PASS if exists else Severity.FAIL,
                    detail=preview,
                )
            )
            details[path] = {
                "status_code": status_code,
                "content_type": content_type,
                "final_url": final_url,
                "preview": preview,
            }

        score = found_count / len(DISCOVERY_PATHS)
        if score == 1.0:
            severity = Severity.PASS
        elif score == 0.0:
            severity = Severity.FAIL
        else:
            severity = Severity.PARTIAL

        return CheckResult(
            category="discovery",
            score=score,
            severity=severity,
            signals=signals,
            details=details,
            recommendations=["Add standardized AI discovery files."] if score < 1.0 else [],
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
    def _is_expected_content_type(path: str, content_type: str | None) -> bool:
        if content_type is None:
            return False

        normalized = content_type.split(";", 1)[0].strip().lower()
        if path.endswith(".txt"):
            return normalized == "text/plain"
        if path.endswith(".json"):
            return normalized == "application/json"
        return False

    @staticmethod
    def _is_expected_final_path(path: str, final_url: str | None) -> bool:
        if final_url is None:
            return False
        return urlparse(final_url).path == path
