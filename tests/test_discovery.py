import pytest

from checks.discovery import DISCOVERY_PATHS, DiscoveryCheck
from core.models import Severity


@pytest.mark.asyncio
async def test_discovery_all_found():
    check = DiscoveryCheck()
    artifacts = {
        path.lstrip("/"): {"status_code": 200, "text": f"content for {path}"}
        for path in DISCOVERY_PATHS
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 1.0
    assert result.severity == Severity.PASS
    assert all(signal.value == "found" for signal in result.signals)


@pytest.mark.asyncio
async def test_discovery_none_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): {"status_code": 404, "text": ""} for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert result.severity == Severity.FAIL


@pytest.mark.asyncio
async def test_discovery_partial_found():
    check = DiscoveryCheck()
    artifacts = {
        DISCOVERY_PATHS[0].lstrip("/"): {"status_code": 200, "text": "ok"},
        DISCOVERY_PATHS[1].lstrip("/"): {"status_code": 200, "text": "ok"},
        DISCOVERY_PATHS[2].lstrip("/"): {"status_code": 404, "text": ""},
        DISCOVERY_PATHS[3].lstrip("/"): {"status_code": 404, "text": ""},
        DISCOVERY_PATHS[4].lstrip("/"): {"status_code": 404, "text": ""},
    }

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.4
    assert result.severity == Severity.PARTIAL


@pytest.mark.asyncio
async def test_discovery_preview_truncated():
    check = DiscoveryCheck()
    long_text = "x" * 300
    artifacts = {
        path.lstrip("/"): {"status_code": 200, "text": long_text}
        for path in DISCOVERY_PATHS
    }

    result = await check.run("https://example.com", artifacts)

    for signal in result.signals:
        assert len(signal.detail) == 120


@pytest.mark.asyncio
async def test_discovery_500_treated_not_found():
    check = DiscoveryCheck()
    artifacts = {path.lstrip("/"): {"status_code": 500, "text": "boom"} for path in DISCOVERY_PATHS}

    result = await check.run("https://example.com", artifacts)

    assert result.score == 0.0
    assert all(signal.value == "not_found" for signal in result.signals)
