from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(Enum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    INFO = "info"
    INCONCLUSIVE = "inconclusive"


@dataclass
class Signal:
    name: str
    value: Any
    severity: Severity
    detail: str = ""


@dataclass
class CheckResult:
    category: str
    score: float  # 0.0 - 1.0
    severity: Severity
    signals: list[Signal] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    url: str
    overall_score: float
    check_results: list[CheckResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
