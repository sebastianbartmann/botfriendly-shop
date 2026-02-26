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
    tier: str  # agent | training_crawler | search_indexer
    description: str


TIER_LABELS = {
    "agent": "AI Shopping Agents",
    "training_crawler": "AI Training Crawlers",
    "search_indexer": "AI Search Indexers & Retrieval",
}

AI_BOTS: list[AIBot] = [
    AIBot("Operator", "OpenAI", "agent", "Autonomous shopping agent by OpenAI"),
    AIBot("ChatGPT Agent", "OpenAI", "agent", "Browses websites on behalf of ChatGPT users"),
    AIBot("AmazonBuyForMe", "Amazon", "agent", "Purchases products on behalf of Amazon customers"),
    AIBot("NovaAct", "Amazon", "agent", "Amazon's browser automation agent"),
    AIBot("GoogleAgent-Mariner", "Google", "agent", "Google's web browsing AI agent"),
    AIBot("GPTBot", "OpenAI", "training_crawler", "Crawls sites to train OpenAI models"),
    AIBot("OAI-SearchBot", "OpenAI", "search_indexer", "Indexes content for SearchGPT results"),
    AIBot("ChatGPT-User", "OpenAI", "search_indexer", "Fetches pages when ChatGPT users ask questions"),
    AIBot("ClaudeBot", "Anthropic", "training_crawler", "Crawls sites to train Anthropic's models"),
    AIBot("Claude-User", "Anthropic", "search_indexer", "Fetches pages when Claude users ask questions"),
    AIBot("Claude-SearchBot", "Anthropic", "search_indexer", "Indexes content for Claude search results"),
    AIBot("Google-Extended", "Google", "training_crawler", "Crawls sites to train Gemini and Vertex AI"),
    AIBot("Gemini-Deep-Research", "Google", "search_indexer", "Fetches pages for Gemini's deep research feature"),
    AIBot("PerplexityBot", "Perplexity", "search_indexer", "Indexes content for Perplexity search"),
    AIBot("Perplexity-User", "Perplexity", "search_indexer", "Fetches pages when Perplexity users ask questions"),
    AIBot("Amazonbot", "Amazon", "search_indexer", "Crawls sites for Alexa answers"),
    AIBot("Meta-ExternalAgent", "Meta", "training_crawler", "Crawls sites to train Meta AI models"),
    AIBot("meta-externalfetcher", "Meta", "search_indexer", "Fetches pages for Meta AI responses"),
    AIBot("Applebot-Extended", "Apple", "training_crawler", "Crawls sites to train Apple Intelligence"),
    AIBot("FacebookBot", "Meta", "training_crawler", "Crawls sites for Meta's language models"),
    AIBot("DeepSeekBot", "DeepSeek", "training_crawler", "Crawls sites to train DeepSeek models"),
    AIBot("Bytespider", "ByteDance", "training_crawler", "ByteDance crawler for LLM training"),
    AIBot("CCBot", "Common Crawl", "training_crawler", "Common Crawl archive, used by many LLM projects"),
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
        if self._is_unreachable_artifact(robots_data):
            bot_states = {bot.name: "not_mentioned" for bot in AI_BOTS}
            details = self._build_details(bot_states, status_code=status_code, reason="robots.txt unreachable")
            signals = [
                Signal(name=bot.name, value="not_mentioned", severity=Severity.INCONCLUSIVE, detail=f"{bot.operator} ({bot.tier})")
                for bot in AI_BOTS
            ]
            signals.extend(self._summary_signals(details))
            return CheckResult(
                category="robots",
                score=0.0,
                severity=Severity.INCONCLUSIVE,
                signals=signals,
                details=details,
                recommendations=[],
            )

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
                recommendations=["Publish a robots.txt policy for AI shopping agents and AI crawlers."],
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
            recommendations=["Set separate robots.txt policies for shopping agents, search indexers, and training crawlers."]
            if score < 1.0
            else [],
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

        def _state_from_directives(directives: list[str] | None) -> str | None:
            if not directives:
                return None
            disallow_all = any(d == "disallow:/" for d in directives)
            allow_any = any(d.startswith("allow:") for d in directives)
            if disallow_all and not allow_any:
                return "blocked"
            return "allowed"

        for bot in AI_BOTS:
            state = _state_from_directives(sections.get(bot.name))
            if state is not None:
                states[bot.name] = state

        wildcard_state = _state_from_directives(sections.get("*"))
        if wildcard_state is not None:
            for bot in AI_BOTS:
                if states[bot.name] == "not_mentioned":
                    states[bot.name] = wildcard_state

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
