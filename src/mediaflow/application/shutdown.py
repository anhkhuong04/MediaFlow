"""Application shutdown coordination boundary."""

from dataclasses import dataclass

from mediaflow.application.models import ShutdownReport
from mediaflow.application.queue_manager import QueueManager


@dataclass(frozen=True, slots=True)
class ShutdownCoordinator:
    queue: QueueManager
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds < 0:
            raise ValueError("Shutdown timeout cannot be negative")

    def execute(self) -> ShutdownReport:
        """Return a truthful report; a timeout never masquerades as a clean stop."""

        return self.queue.shutdown(timeout_seconds=self.timeout_seconds)
