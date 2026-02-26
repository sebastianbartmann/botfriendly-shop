import pytest

from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from core.models import Severity


def _content_type_for(path: str) -> str:
    if path.endswith(".txt"):
        return "text/plain"
    if path.endswith(".json"):
        return "application/json"
    return "application/yaml"


def _artifact(path: str, status_code: int, text: str, content_type: str | None = None, final_url: str | None = None) -> dict:
    return {
        "status_code": status_code,
        "text": text,
        "content_type": content_type if content_type is not None else _content_type_for(path),
        "final_url": final_url if final_url is not None else f"https://example.com{path}",
    }


@pytest.mark.asyncio
async def test_discovery_all_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): _artifact(path, 200, "ok") for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert all(signal.value == "found" for signal in result.signals)


@pytest.mark.asyncio
async def test_discovery_none_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): _artifact(path, 404, "") for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_discovery_500_treated_as_inconclusive():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): _artifact(path, 500, "boom") for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.INCONCLUSIVE
    assert len(result.signals) == 1
    assert result.details["reason"] == "All discovery endpoints were unreachable"


@pytest.mark.asyncio
async def test_discovery_yaml_content_type_with_charset_counts_as_found():
    check = DiscoveryCheck()
    path = "/.well-known/openai.yaml"
    artifacts = {p.lstrip("/"): _artifact(p, 404, "") for p in DISCOVERY_PATHS}
    artifacts[path.lstrip("/")] = _artifact(path, 200, "openapi: 3.1.0", content_type="application/yaml; charset=utf-8")

    result = await check.run("https://example.com", artifacts)

    signal = next(s for s in result.signals if s.name == path)
    assert signal.value == "found"


@pytest.mark.asyncio
async def test_discovery_redirected_path_treated_not_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): _artifact(path, 200, "ok", final_url="https://example.com/login") for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert all(signal.value == "not_found" for signal in result.signals)
