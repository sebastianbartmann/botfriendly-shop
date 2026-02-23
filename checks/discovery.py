from __future__ import annotations

from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from core.models import CheckResult, Severity, Signal

DISCOVERY_PATHS = [
    "/llms.txt",
    "/llms-full.txt",
    "/.well-known/ai-plugin.json",
    "/.well-known/agent.json",
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
            text = response_data.get("text", "") if status_code == 200 else ""
            exists = status_code == 200
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
            details[path] = {"status_code": status_code, "preview": preview}

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
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}
