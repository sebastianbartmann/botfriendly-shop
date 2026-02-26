import httpx
import pytest

from checks.robots import AI_BOTS, RobotsCheck
from core.models import Severity


def _build_robots_body(rule: str) -> str:
    return "\n".join([f"User-agent: {bot.name}\n{rule}" for bot in AI_BOTS])


def _build_mixed_tier_body(*, agent_rule: str, non_agent_rule: str) -> str:
    chunks: list[str] = []
    for bot in AI_BOTS:
        rule = agent_rule if bot.tier == "agent" else non_agent_rule
        chunks.append(f"User-agent: {bot.name}\n{rule}")
    return "\n".join(chunks)


@pytest.mark.asyncio
async def test_robots_all_allowed():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": _build_robots_body("Allow: /")}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    bot_signals = [s for s in result.signals if not s.name.startswith("tier:") and not s.name.startswith("overall:")]
    assert all(signal.value == "allowed" for signal in bot_signals)

    tiers = result.details["tiers"]
    assert tiers["agent"] == {"label": "AI Shopping Agents", "allowed": 5, "blocked": 0, "not_mentioned": 0, "total": 5}
    assert tiers["search_indexer"] == {"label": "AI Search Indexers & Retrieval", "allowed": 9, "blocked": 0, "not_mentioned": 0, "total": 9}
    assert tiers["training_crawler"] == {"label": "AI Training Crawlers", "allowed": 9, "blocked": 0, "not_mentioned": 0, "total": 9}
    assert result.details["overall"] == {"allowed": 23, "blocked": 0, "not_mentioned": 0, "total": 23}
    assert result.details["blocked_operators"] == []


@pytest.mark.asyncio
async def test_robots_agents_allowed_non_agents_blocked_mixed():
    check = RobotsCheck()
    artifacts = {
        "robots.txt": {
            "status_code": 200,
            "text": _build_mixed_tier_body(agent_rule="Allow: /", non_agent_rule="Disallow: /"),
        }
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == pytest.approx(5 / 23)
    assert result.severity == Severity.PARTIAL

    tiers = result.details["tiers"]
    assert tiers["agent"]["allowed"] == 5
    assert tiers["agent"]["blocked"] == 0
    assert tiers["search_indexer"]["allowed"] == 0
    assert tiers["search_indexer"]["blocked"] == 9
    assert tiers["training_crawler"]["allowed"] == 0
    assert tiers["training_crawler"]["blocked"] == 9
    assert result.details["overall"] == {"allowed": 5, "blocked": 18, "not_mentioned": 0, "total": 23}
    assert result.details["blocked_operators"] == ["Amazon", "Anthropic", "Apple", "ByteDance", "Common Crawl", "DeepSeek", "Google", "Meta", "OpenAI", "Perplexity"]


@pytest.mark.asyncio
async def test_robots_all_blocked():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": _build_robots_body("Disallow: /")}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    bot_signals = [s for s in result.signals if not s.name.startswith("tier:") and not s.name.startswith("overall:")]
    assert all(signal.value == "blocked" for signal in bot_signals)


@pytest.mark.asyncio
async def test_robots_tier_stats_details_include_not_mentioned_counts():
    check = RobotsCheck()
    partial = "\n".join([
        "User-agent: Operator\nAllow: /",
        "User-agent: GPTBot\nDisallow: /",
    ])
    artifacts = {"robots.txt": {"status_code": 200, "text": partial}}

    result = await check.run("https://example.com", artifacts)

    tiers = result.details["tiers"]
    assert tiers["agent"] == {"label": "AI Shopping Agents", "allowed": 1, "blocked": 0, "not_mentioned": 4, "total": 5}
    assert tiers["search_indexer"] == {"label": "AI Search Indexers & Retrieval", "allowed": 0, "blocked": 0, "not_mentioned": 9, "total": 9}
    assert tiers["training_crawler"] == {"label": "AI Training Crawlers", "allowed": 0, "blocked": 1, "not_mentioned": 8, "total": 9}
    assert result.details["overall"] == {"allowed": 1, "blocked": 1, "not_mentioned": 21, "total": 23}


@pytest.mark.asyncio
async def test_robots_missing_file():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 404, "text": ""}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_robots_fetch_error_status_none_marks_all_not_mentioned():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": None, "text": ""}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.INCONCLUSIVE
    bot_signals = [s for s in result.signals if not s.name.startswith("tier:") and not s.name.startswith("overall:")]
    assert all(signal.value == "not_mentioned" for signal in bot_signals)


@pytest.mark.asyncio
async def test_robots_wildcard_disallow_applies_to_unmentioned_bots():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": "User-agent: *\nDisallow: /"}}

    result = await check.run("https://example.com", artifacts)

    bot_signals = [s for s in result.signals if not s.name.startswith("tier:") and not s.name.startswith("overall:")]
    assert all(signal.value == "blocked" for signal in bot_signals)


@pytest.mark.asyncio
async def test_robots_bot_specific_allow_overrides_wildcard_disallow():
    check = RobotsCheck()
    artifacts = {
        "robots.txt": {
            "status_code": 200,
            "text": "\n".join([
                "User-agent: *",
                "Disallow: /",
                "User-agent: Operator",
                "Allow: /",
            ]),
        }
    }

    result = await check.run("https://example.com", artifacts)

    operator_signal = next(signal for signal in result.signals if signal.name == "Operator")
    gptbot_signal = next(signal for signal in result.signals if signal.name == "GPTBot")
    assert operator_signal.value == "allowed"
    assert gptbot_signal.value == "blocked"


@pytest.mark.asyncio
async def test_robots_tier_summary_severity_all_not_mentioned_is_inconclusive():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": ""}}

    result = await check.run("https://example.com", artifacts)

    tier_signals = [s for s in result.signals if s.name.startswith("tier:")]
    overall_signal = next(s for s in result.signals if s.name == "overall:robots")
    assert all(signal.severity == Severity.INCONCLUSIVE for signal in tier_signals)
    assert overall_signal.severity == Severity.INCONCLUSIVE


@pytest.mark.asyncio
async def test_robots_malformed_treated_as_not_mentioned():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": "this is not robots syntax"}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    bot_signals = [s for s in result.signals if not s.name.startswith("tier:") and not s.name.startswith("overall:")]
    assert all(signal.value == "not_mentioned" for signal in bot_signals)


@pytest.mark.asyncio
async def test_robots_fetch_on_missing_artifact(monkeypatch, fake_get_factory):
    base = "https://example.com/"
    robots = _build_robots_body("Allow: /")
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        fake_get_factory({f"{base}robots.txt": (200, robots)}),
        raising=True,
    )

    check = RobotsCheck()
    result = await check.run("https://example.com", {})

    assert result.score == 1.0
