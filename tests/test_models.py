from dataclasses import asdict

from core.models import CheckResult, ScanResult, Severity, Signal


def test_check_result_creation_with_all_fields():
    signal = Signal(name="llms", value=True, severity=Severity.PASS, detail="found")
    result = CheckResult(
        category="discovery",
        score=0.75,
        severity=Severity.PARTIAL,
        signals=[signal],
        details={"llms.txt": 200},
        recommendations=["Add llms-full.txt"],
    )

    assert result.category == "discovery"
    assert result.score == 0.75
    assert result.severity == Severity.PARTIAL
    assert result.signals == [signal]
    assert result.details == {"llms.txt": 200}
    assert result.recommendations == ["Add llms-full.txt"]


def test_signal_creation():
    signal = Signal(name="robots", value="allowed", severity=Severity.PASS)
    assert signal.name == "robots"
    assert signal.value == "allowed"
    assert signal.severity == Severity.PASS


def test_scan_result_creation_with_metadata():
    check = CheckResult(category="robots", score=1.0, severity=Severity.PASS)
    result = ScanResult(
        url="https://example.com",
        overall_score=0.9,
        check_results=[check],
        metadata={"grade": "A+", "source": "test"},
    )

    assert result.url == "https://example.com"
    assert result.overall_score == 0.9
    assert result.check_results == [check]
    assert result.metadata == {"grade": "A+", "source": "test"}


def test_signal_creation_with_all_severity_levels():
    levels = [Severity.PASS, Severity.PARTIAL, Severity.FAIL, Severity.INFO, Severity.INCONCLUSIVE]
    signals = [Signal(name=level.value, value=True, severity=level, detail="x") for level in levels]

    assert [signal.severity for signal in signals] == levels


def test_check_result_defaults_are_isolated():
    first = CheckResult(category="robots", score=1.0, severity=Severity.PASS)
    second = CheckResult(category="sitemap", score=0.5, severity=Severity.PARTIAL)

    first.signals.append(Signal(name="a", value=True, severity=Severity.PASS))
    first.recommendations.append("x")
    first.details["a"] = 1

    assert second.signals == []
    assert second.recommendations == []
    assert second.details == {}


def test_scan_result_defaults_are_isolated():
    first = ScanResult(url="https://a.com", overall_score=0.1)
    second = ScanResult(url="https://b.com", overall_score=0.2)

    first.metadata["k"] = "v"
    assert second.metadata == {}


def test_serialization_with_asdict():
    result = ScanResult(
        url="https://example.com",
        overall_score=0.8,
        check_results=[
            CheckResult(
                category="robots",
                score=1.0,
                severity=Severity.PASS,
                signals=[Signal(name="GPTBot", value="allowed", severity=Severity.PASS)],
            )
        ],
    )

    data = asdict(result)
    assert data["url"] == "https://example.com"
    assert data["check_results"][0]["signals"][0]["name"] == "GPTBot"


def test_severity_values():
    assert Severity.PASS.value == "pass"
    assert Severity.PARTIAL.value == "partial"
    assert Severity.FAIL.value == "fail"
    assert Severity.INFO.value == "info"
    assert Severity.INCONCLUSIVE.value == "inconclusive"
    assert [member.value for member in Severity] == ["pass", "partial", "fail", "info", "inconclusive"]
