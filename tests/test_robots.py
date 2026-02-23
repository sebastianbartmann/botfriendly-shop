import httpx
import pytest

from checks.robots import AI_BOTS, RobotsCheck
from core.models import Severity


def _build_robots_body(rule: str) -> str:
    return "\n".join([f"User-agent: {bot}\n{rule}" for bot in AI_BOTS])


@pytest.mark.asyncio
async def test_robots_all_allowed():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": _build_robots_body("Allow: /")}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert all(signal.value == "allowed" for signal in result.signals)


@pytest.mark.asyncio
async def test_robots_all_blocked():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": _build_robots_body("Disallow: /")}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    assert all(signal.value == "blocked" for signal in result.signals)


@pytest.mark.asyncio
async def test_robots_mixed():
    check = RobotsCheck()
    allowed = "\n".join([f"User-agent: {AI_BOTS[i]}\nAllow: /" for i in range(5)])
    blocked = "\n".join([f"User-agent: {AI_BOTS[i]}\nDisallow: /" for i in range(5, 10)])
    artifacts = {"robots.txt": {"status_code": 200, "text": f"{allowed}\n{blocked}"}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.5
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_robots_missing_file():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 404, "text": ""}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_robots_malformed_treated_as_not_mentioned():
    check = RobotsCheck()
    artifacts = {"robots.txt": {"status_code": 200, "text": "this is not robots syntax"}}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL
    assert all(signal.value == "not_mentioned" for signal in result.signals)


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
