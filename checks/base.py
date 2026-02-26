from abc import ABC, abstractmethod

from core.models import CheckResult, Severity, Signal

INCONCLUSIVE_HTTP_STATUSES = {401, 403, 408, 425, 429, 451, 500, 502, 503, 504}


class BaseCheck(ABC):
    requires_browser: bool = False

    @staticmethod
    def _status_code(artifact: dict | None) -> int | None:
        if not isinstance(artifact, dict):
            return None
        status = artifact.get("status_code")
        return status if isinstance(status, int) else None

    @classmethod
    def _is_unreachable_artifact(cls, artifact: dict | None) -> bool:
        status = cls._status_code(artifact)
        if status is None:
            return True
        return status in INCONCLUSIVE_HTTP_STATUSES

    def _inconclusive_result(
        self,
        *,
        category: str,
        reason: str,
        details: dict | None = None,
        recommendations: list[str] | None = None,
    ) -> CheckResult:
        payload = dict(details or {})
        payload.setdefault("reason", reason)
        return CheckResult(
            category=category,
            score=0.0,
            severity=Severity.INCONCLUSIVE,
            signals=[Signal(name="fetch_status", value="inconclusive", severity=Severity.INCONCLUSIVE, detail=reason)],
            details=payload,
            recommendations=recommendations or [],
        )

    @abstractmethod
    async def run(self, url: str, artifacts: dict) -> CheckResult:
        """Run the check. artifacts contains data from HTTP pass."""
        raise NotImplementedError
