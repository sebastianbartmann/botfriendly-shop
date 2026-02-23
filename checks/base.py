from abc import ABC, abstractmethod

from core.models import CheckResult


class BaseCheck(ABC):
    requires_browser: bool = False

    @abstractmethod
    async def run(self, url: str, artifacts: dict) -> CheckResult:
        """Run the check. artifacts contains data from HTTP pass."""
        raise NotImplementedError
