import pytest

from core.models import CheckResult, Severity
from core.scoring import calculate_overall_score, get_grade


def _check(category: str, score: float) -> CheckResult:
    return CheckResult(category=category, score=score, severity=Severity.PASS)


def test_calculate_overall_score_all_perfect():
    checks = [
        _check("structured_data", 1.0),
        _check("product_parseability", 1.0),
        _check("robots", 1.0),
        _check("discovery", 1.0),
        _check("sitemap", 1.0),
        _check("feeds", 1.0),
        _check("api_surface", 1.0),
    ]
    assert calculate_overall_score(checks) == pytest.approx(1.0)


def test_calculate_overall_score_all_zero():
    checks = [
        _check("structured_data", 0.0),
        _check("product_parseability", 0.0),
        _check("robots", 0.0),
        _check("discovery", 0.0),
        _check("sitemap", 0.0),
        _check("feeds", 0.0),
        _check("api_surface", 0.0),
    ]
    assert calculate_overall_score(checks) == pytest.approx(0.0)


def test_calculate_overall_score_mixed_weights():
    checks = [
        _check("structured_data", 1.0),      # weight 20
        _check("product_parseability", 0.0),  # weight 20
        _check("robots", 1.0),                # weight 15
        _check("discovery", 0.0),             # weight 10
        _check("sitemap", 1.0),               # weight 10
        _check("feeds", 0.0),                 # weight 15
        _check("api_surface", 1.0),           # weight 10
    ]
    # (20 + 15 + 10 + 10) / 100
    assert calculate_overall_score(checks) == pytest.approx(0.55)


def test_calculate_overall_score_unknown_category_uses_default_weight():
    checks = [
        _check("structured_data", 1.0),
        _check("unknown", 0.0),
    ]
    expected = 20.0 / 30.0
    assert calculate_overall_score(checks) == pytest.approx(expected)


def test_calculate_overall_score_empty_results_is_zero():
    assert calculate_overall_score([]) == 0.0


def test_get_grade_boundaries():
    assert get_grade(0.9) == "A+"
    assert get_grade(0.89) == "A"
    assert get_grade(0.8) == "A"
    assert get_grade(0.79) == "B"
    assert get_grade(0.65) == "B"
    assert get_grade(0.64) == "C"
    assert get_grade(0.5) == "C"
    assert get_grade(0.49) == "D"
    assert get_grade(0.35) == "D"
    assert get_grade(0.34) == "F"
    assert get_grade(0.0) == "F"
