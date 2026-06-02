"""Central event bus for audit events with pub/sub pattern."""

import asyncio
import logging
from asyncio import Queue
from dataclasses import dataclass, field

from saz.domain.event_schema import Event

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    """A subscriber to events for a specific run."""

    run_id: str
    queue: Queue
    # Set True when an event had to be dropped because the queue was full, so
    # the stream layer can signal a gap and the client can refetch via REST.
    dropped: bool = field(default=False)

    def __hash__(self) -> int:
        """Make subscription hashable for set operations."""
        return hash((self.run_id, id(self.queue)))


class EventBus:
    """
    Central event bus for audit events.

    Provides pub/sub pattern for real-time event streaming to WebSocket clients.
    """

    def __init__(self):
        self._subscriptions: set[Subscription] = set()
        self._lock = asyncio.Lock()

    def subscribe(self, run_id: str, queue: Queue) -> Subscription:
        """
        Subscribe to events for a specific run.

        Args:
            run_id: Run ID to subscribe to
            queue: Async queue to receive events

        Returns:
            Subscription handle for unsubscribing
        """
        sub = Subscription(run_id=run_id, queue=queue)
        self._subscriptions.add(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        """
        Unsubscribe from events.

        Args:
            subscription: Subscription handle to remove
        """
        self._subscriptions.discard(subscription)

    async def publish(self, events: list[Event]) -> None:
        """
        Publish events to all relevant subscribers.

        Events are routed to subscribers based on run_id matching.

        Args:
            events: List of events to publish
        """
        if not events:
            return

        for event in events:
            # Find all subscriptions for this run
            for sub in list(self._subscriptions):  # Copy to avoid modification during iteration
                if sub.run_id == event.run_id:
                    try:
                        # Non-blocking put - if queue is full, mark a gap.
                        sub.queue.put_nowait(event)
                    except asyncio.QueueFull:
                        # Slow consumer: record the drop so the stream can tell
                        # the client to refetch canonical state via REST. Never
                        # silently lose an event without a trace.
                        sub.dropped = True
                        logger.warning(
                            "event_bus_drop run_id=%s event_type=%s seq=%s "
                            "(slow consumer; client should refetch via REST)",
                            event.run_id,
                            getattr(event.event_type, "value", event.event_type),
                            getattr(event, "seq", None),
                        )
                    except Exception:
                        # Subscription may be closed, ignore
                        pass

    async def publish_to_run(self, run_id: str, event: Event) -> None:
        """
        Publish a single event to subscribers of a specific run.

        Args:
            run_id: Run ID to publish to
            event: Event to publish
        """
        await self.publish([event])

    def subscriber_count(self, run_id: str) -> int:
        """
        Get number of active subscribers for a run.

        Args:
            run_id: Run ID to check

        Returns:
            Number of active subscriptions
        """
        return sum(1 for sub in self._subscriptions if sub.run_id == run_id)


# Global singleton instance
event_bus = EventBus()
