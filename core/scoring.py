from __future__ import annotations

from core.models import CheckResult

# Default weights for v1 — equal weights, can be tuned later
CATEGORY_WEIGHTS = {
    "structured_data": 20,
    "product_parseability": 20,
    "robots": 15,
    "discovery": 10,
    "sitemap": 10,
    "feeds": 15,
    "api_surface": 10,
    "seo_meta": 10,
}


def calculate_overall_score(check_results: list[CheckResult]) -> float:
    """Weighted average of check scores. Returns 0.0-1.0."""
    if not check_results:
        return 0.0

    default_unknown_weight = 10.0

    weighted_sum = 0.0
    total_weight = 0.0
    for result in check_results:
        weight = CATEGORY_WEIGHTS.get(result.category, default_unknown_weight)
        weighted_sum += result.score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight


def get_grade(score: float) -> str:
    """A+ (0.9+), A (0.8+), B (0.65+), C (0.5+), D (0.35+), F (<0.35)."""
    if score >= 0.9:
        return "A+"
    if score >= 0.8:
        return "A"
    if score >= 0.65:
        return "B"
    if score >= 0.5:
        return "C"
    if score >= 0.35:
        return "D"
    return "F"
