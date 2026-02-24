from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from checks.base import BaseCheck
from core.models import CheckResult, Severity, Signal


@dataclass(frozen=True)
class AIBot:
    name: str
    operator: str
    tier: str  # agent | crawler


TIER_LABELS = {
    "agent": "AI Shopping Agents",
    "crawler": "AI Crawlers & Search",
}

AI_BOTS: list[AIBot] = [
    AIBot("Operator", "OpenAI", "agent"),
    AIBot("ChatGPT Agent", "OpenAI", "agent"),
    AIBot("AmazonBuyForMe", "Amazon", "agent"),
    AIBot("NovaAct", "Amazon", "agent"),
    AIBot("GoogleAgent-Mariner", "Google", "agent"),
    AIBot("GPTBot", "OpenAI", "crawler"),
    AIBot("OAI-SearchBot", "OpenAI", "crawler"),
    AIBot("ChatGPT-User", "OpenAI", "crawler"),
    AIBot("ClaudeBot", "Anthropic", "crawler"),
    AIBot("Claude-User", "Anthropic", "crawler"),
    AIBot("Claude-SearchBot", "Anthropic", "crawler"),
    AIBot("Google-Extended", "Google", "crawler"),
    AIBot("Gemini-Deep-Research", "Google", "crawler"),
    AIBot("PerplexityBot", "Perplexity", "crawler"),
    AIBot("Perplexity-User", "Perplexity", "crawler"),
    AIBot("Amazonbot", "Amazon", "crawler"),
    AIBot("Meta-ExternalAgent", "Meta", "crawler"),
    AIBot("meta-externalfetcher", "Meta", "crawler"),
    AIBot("Applebot-Extended", "Apple", "crawler"),
    AIBot("FacebookBot", "Meta", "crawler"),
    AIBot("DeepSeekBot", "DeepSeek", "crawler"),
    AIBot("Bytespider", "ByteDance", "crawler"),
    AIBot("CCBot", "Common Crawl", "crawler"),
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
            bot_states = {bot.name: "not_mentioned" for bot in AI_BOTS}
            details = self._build_details(bot_states, status_code=status_code, reason="robots.txt missing or unreadable")
            signals = [
                Signal(name=bot.name, value="not_mentioned", severity=Severity.INCONCLUSIVE, detail=f"{bot.operator} ({bot.tier})")
                for bot in AI_BOTS
            ]
            signals.extend(self._summary_signals(details))
            return CheckResult(
                category="robots",
                score=0.0,
                severity=Severity.FAIL,
                signals=signals,
                details=details,
                recommendations=["Publish a robots.txt policy for AI bots and search crawlers."],
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

        details = self._build_details(bot_states, status_code=status_code)
        signals = []
        for bot in AI_BOTS:
            state = bot_states[bot.name]
            signal_severity = Severity.PASS if state == "allowed" else Severity.FAIL if state == "blocked" else Severity.INCONCLUSIVE
            signals.append(Signal(name=bot.name, value=state, severity=signal_severity, detail=f"{bot.operator} ({bot.tier})"))
        signals.extend(self._summary_signals(details))

        return CheckResult(
            category="robots",
            score=score,
            severity=severity,
            signals=signals,
            details=details,
            recommendations=["Allow major AI shopping agents and crawlers in robots.txt where appropriate."] if score < 1.0 else [],
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
        states: dict[str, str] = {bot.name: "not_mentioned" for bot in AI_BOTS}
        sections: dict[str, list[str]] = {}

        current_agents: list[str] = []
        current_group_has_directives = False
        for raw_line in robots_txt.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue

            key, value = [part.strip() for part in line.split(":", 1)]
            key_lower = key.lower()
            if key_lower == "user-agent":
                if current_group_has_directives:
                    current_agents = [value]
                    current_group_has_directives = False
                else:
                    current_agents.append(value)
                sections.setdefault(value, [])
            elif key_lower in {"allow", "disallow"} and current_agents:
                current_group_has_directives = True
                for agent in current_agents:
                    sections.setdefault(agent, []).append(f"{key_lower}:{value}")

        for bot in AI_BOTS:
            directives = sections.get(bot.name)
            if not directives:
                continue
            disallow_all = any(d == "disallow:/" for d in directives)
            allow_any = any(d.startswith("allow:") for d in directives)
            if disallow_all and not allow_any:
                states[bot.name] = "blocked"
            else:
                states[bot.name] = "allowed"

        return states

    @staticmethod
    def _summary_severity(allowed: int, blocked: int, not_mentioned: int, total: int) -> Severity:
        if allowed == total:
            return Severity.PASS
        if blocked == total:
            return Severity.FAIL
        if not_mentioned == total:
            return Severity.INCONCLUSIVE
        return Severity.PARTIAL

    @classmethod
    def _build_details(cls, bot_states: dict[str, str], *, status_code: int | None, reason: str | None = None) -> dict:
        tiers: dict[str, dict[str, int | str]] = {
            tier: {"label": label, "allowed": 0, "blocked": 0, "not_mentioned": 0, "total": 0}
            for tier, label in TIER_LABELS.items()
        }
        overall = {"allowed": 0, "blocked": 0, "not_mentioned": 0, "total": len(AI_BOTS)}

        blocked_operators: set[str] = set()
        for bot in AI_BOTS:
            state = bot_states.get(bot.name, "not_mentioned")
            tier_stats = tiers[bot.tier]
            tier_stats["total"] += 1
            tier_stats[state] += 1
            overall[state] += 1
            if state == "blocked":
                blocked_operators.add(bot.operator)

        details = {
            "status_code": status_code,
            "tiers": tiers,
            "overall": overall,
            "blocked_operators": sorted(blocked_operators),
        }
        if reason:
            details["reason"] = reason
        return details

    @classmethod
    def _summary_signals(cls, details: dict) -> list[Signal]:
        summary: list[Signal] = []
        tiers = details.get("tiers", {})
        for tier, stats in tiers.items():
            allowed = int(stats.get("allowed", 0))
            blocked = int(stats.get("blocked", 0))
            not_mentioned = int(stats.get("not_mentioned", 0))
            total = int(stats.get("total", 0))
            summary.append(
                Signal(
                    name=f"tier:{tier}",
                    value={"allowed": allowed, "blocked": blocked, "not_mentioned": not_mentioned, "total": total},
                    severity=cls._summary_severity(allowed, blocked, not_mentioned, total),
                    detail=str(stats.get("label", tier)),
                )
            )

        overall = details.get("overall", {})
        o_allowed = int(overall.get("allowed", 0))
        o_blocked = int(overall.get("blocked", 0))
        o_not = int(overall.get("not_mentioned", 0))
        o_total = int(overall.get("total", 0))
        summary.append(
            Signal(
                name="overall:robots",
                value={"allowed": o_allowed, "blocked": o_blocked, "not_mentioned": o_not, "total": o_total},
                severity=cls._summary_severity(o_allowed, o_blocked, o_not, o_total),
            )
        )
        return summary
