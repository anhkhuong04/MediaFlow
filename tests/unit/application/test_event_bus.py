from datetime import UTC, datetime
from threading import Thread, current_thread

from mediaflow.application import AnalysisFailed, ApplicationEvent, InProcessEventBus
from mediaflow.domain import Failure, FailureCategory, SourceUrl, UtcTimestamp


def test_event_subscription_is_thread_agnostic_isolated_and_idempotently_closed() -> None:
    bus = InProcessEventBus()
    received = []
    publisher_threads = []

    def receive(event: ApplicationEvent) -> None:
        received.append(event)
        publisher_threads.append(current_thread().name)

    subscription = bus.subscribe(receive)
    bus.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError(str(event))))
    event = AnalysisFailed(
        SourceUrl("https://example.com/media"),
        Failure(FailureCategory.NETWORK, "analysis.network", True),
        UtcTimestamp(datetime(2026, 9, 7, tzinfo=UTC)),
    )
    worker = Thread(target=bus.publish, args=(event,), name="event-worker")
    worker.start()
    worker.join(timeout=5)

    assert received == [event]
    assert publisher_threads == ["event-worker"]
    subscription.close()
    subscription.close()
    bus.publish(event)
    assert received == [event]
