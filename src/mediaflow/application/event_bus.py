"""Thread-agnostic in-process events for application and presentation bridges."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from mediaflow.application.events import ApplicationEvent

_LOGGER = logging.getLogger("mediaflow.events")


class InProcessEventBus:
    """Invoke subscribers on the publishing thread; Qt must marshal downstream."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_id = 0
        self._subscribers: dict[int, Callable[[ApplicationEvent], None]] = {}

    def publish(self, event: ApplicationEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                # A presentation observer cannot roll back committed state or
                # abort a worker. The safe logger suppresses arbitrary details.
                _LOGGER.warning("application.failed")

    def subscribe(self, subscriber: Callable[[ApplicationEvent], None]) -> "EventBusSubscription":
        with self._lock:
            subscription_id = self._next_id
            self._next_id += 1
            self._subscribers[subscription_id] = subscriber
        return EventBusSubscription(self, subscription_id)

    def _unsubscribe(self, subscription_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscription_id, None)


@dataclass(slots=True)
class EventBusSubscription:
    _bus: InProcessEventBus
    _subscription_id: int
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._bus._unsubscribe(self._subscription_id)

    def __enter__(self) -> "EventBusSubscription":
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()
