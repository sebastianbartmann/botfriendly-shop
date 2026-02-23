from __future__ import annotations

from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from core.models import CheckResult, Severity, Signal

AI_BOTS = [
    "GPTBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-Web",
    "Amazonbot",
    "CCBot",
    "Google-Extended",
    "PerplexityBot",
    "Bytespider",
    "FacebookBot",
]


class RobotsCheck(BaseCheck):
    requires_browser = False

    async def run(self, url: str, artifacts: dict) -> CheckResult:
        robots_data = artifacts.get("robots.txt")
        if robots_data is None:
            robots_url = urljoin(url.rstrip("/") + "/", "robots.txt")
            robots_data = await self._fetch(robots_url)

        status_code = robots_data.get("status_code")
        body = robots_data.get("text", "")
        if status_code != 200 or not isinstance(body, str):
            signals = [
                Signal(name=bot, value="not_mentioned", severity=Severity.INCONCLUSIVE)
                for bot in AI_BOTS
            ]
            return CheckResult(
                category="robots",
                score=0.0,
                severity=Severity.FAIL,
                signals=signals,
                details={"reason": "robots.txt missing or unreadable", "status_code": status_code},
                recommendations=["Publish a robots.txt policy for AI crawlers."],
            )

        bot_states = self._parse_bot_states(body)
        allowed_count = sum(1 for state in bot_states.values() if state == "allowed")
        score = allowed_count / len(AI_BOTS)

        if score == 1.0:
            severity = Severity.PASS
        elif score == 0.0:
            severity = Severity.FAIL
        else:
            severity = Severity.PARTIAL

        signals = [
            Signal(
                name=bot,
                value=state,
                severity=Severity.PASS if state == "allowed" else Severity.FAIL,
            )
            for bot, state in bot_states.items()
        ]

        return CheckResult(
            category="robots",
            score=score,
            severity=severity,
            signals=signals,
            details={"status_code": status_code},
            recommendations=["Allow major AI bots in robots.txt where appropriate."] if score < 1.0 else [],
        )

    async def _fetch(self, url: str) -> dict:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError:
                return {"status_code": None, "text": ""}
        return {"status_code": response.status_code, "text": response.text}

    @staticmethod
    def _parse_bot_states(robots_txt: str) -> dict[str, str]:
        # Default state is not_mentioned unless a specific user-agent block defines behavior.
        states: dict[str, str] = {bot: "not_mentioned" for bot in AI_BOTS}
        sections: dict[str, list[str]] = {}

        current_agents: list[str] = []
        for raw_line in robots_txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue

            key, value = [part.strip() for part in line.split(":", 1)]
            key_lower = key.lower()
            if key_lower == "user-agent":
                agent = value
                if current_agents and any(a in sections for a in current_agents):
                    current_agents = [agent]
                else:
                    current_agents.append(agent)
                sections.setdefault(agent, [])
            elif key_lower in {"allow", "disallow"} and current_agents:
                for agent in current_agents:
                    sections.setdefault(agent, []).append(f"{key_lower}:{value}")

        for bot in AI_BOTS:
            directives = sections.get(bot)
            if not directives:
                continue
            disallow_all = any(d == "disallow:/" for d in directives)
            allow_any = any(d.startswith("allow:") for d in directives)
            if disallow_all and not allow_any:
                states[bot] = "blocked"
            else:
                states[bot] = "allowed"

        return states
