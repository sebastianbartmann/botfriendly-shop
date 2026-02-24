import pytest

from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from core.models import Severity


def _content_type_for(path: str) -> str:
    return "text/plain" if path.endswith(".txt") else "application/json"


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
    artifacts = {
        path.lstrip("/"): _artifact(path, 200, f"content for {path}")
        for path in DISCOVERY_PATHS
    }

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
async def test_discovery_partial_found():
    check = DiscoveryCheck()
    artifacts = {
        DISCOVERY_PATHS[0].lstrip("/"): _artifact(DISCOVERY_PATHS[0], 200, "ok"),
        DISCOVERY_PATHS[1].lstrip("/"): _artifact(DISCOVERY_PATHS[1], 200, "ok"),
        DISCOVERY_PATHS[2].lstrip("/"): _artifact(DISCOVERY_PATHS[2], 404, ""),
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == pytest.approx(2 / 3)
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_discovery_preview_truncated():
    check = DiscoveryCheck()
    long_text = "x" * 300
    artifacts = {
        path.lstrip("/"): _artifact(path, 200, long_text)
        for path in DISCOVERY_PATHS
    }

    result = await check.run("https://example.com", artifacts)

    for signal in result.signals:
        assert len(signal.detail) == 120


@pytest.mark.asyncio
async def test_discovery_500_treated_not_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): _artifact(path, 500, "boom") for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert all(signal.value == "not_found" for signal in result.signals)


@pytest.mark.asyncio
async def test_discovery_wrong_content_type_treated_not_found():
    check = DiscoveryCheck()
    artifacts = {
        path.lstrip("/"): _artifact(path, 200, "<html>redirect page</html>", content_type="text/html")
        for path in DISCOVERY_PATHS
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert all(signal.value == "not_found" for signal in result.signals)


@pytest.mark.asyncio
async def test_discovery_redirected_path_treated_not_found():
    check = DiscoveryCheck()
    artifacts = {
        path.lstrip("/"): _artifact(path, 200, "ok", final_url="https://example.com/login")
        for path in DISCOVERY_PATHS
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert all(signal.value == "not_found" for signal in result.signals)
