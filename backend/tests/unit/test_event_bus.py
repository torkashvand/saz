"""Tests for EventBus pub/sub."""

import asyncio
from asyncio import Queue

import pytest

from saz.audit.event_bus import EventBus
from saz.domain.event_schema import Event, EventType


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    """EventBus delivers events to subscribers."""
    bus = EventBus()

    # Subscribe to run_1
    queue = Queue()
    sub = bus.subscribe("run_1", queue)

    # Publish event
    event = Event(
        event_type=EventType.RUN_STARTED,
        run_id="run_1",
        summary="Test",
    )

    await bus.publish([event])

    # Receive event
    received_event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received_event.event_type == EventType.RUN_STARTED
    assert received_event.run_id == "run_1"

    # Cleanup
    bus.unsubscribe(sub)


@pytest.mark.asyncio
async def test_per_run_isolation():
    """Events only go to subscribers of that run."""
    bus = EventBus()

    # Subscribe to different runs
    queue1 = Queue()
    queue2 = Queue()
    sub1 = bus.subscribe("run_1", queue1)
    sub2 = bus.subscribe("run_2", queue2)

    # Publish to run_1
    event1 = Event(
        event_type=EventType.RUN_STARTED,
        run_id="run_1",
        summary="Run 1",
    )
    await bus.publish([event1])

    # Only queue1 receives it
    received1 = await asyncio.wait_for(queue1.get(), timeout=0.5)
    assert received1.run_id == "run_1"

    # queue2 should be empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue2.get(), timeout=0.1)

    # Cleanup
    bus.unsubscribe(sub1)
    bus.unsubscribe(sub2)


@pytest.mark.asyncio
async def test_multiple_subscribers_same_run():
    """Multiple subscribers receive same events."""
    bus = EventBus()

    # Two subscribers to same run
    queue1 = Queue()
    queue2 = Queue()
    sub1 = bus.subscribe("run_1", queue1)
    sub2 = bus.subscribe("run_1", queue2)

    # Publish event
    event = Event(
        event_type=EventType.STEP_STARTED,
        run_id="run_1",
        step_id="step_1",
        summary="Step 1",
    )
    await bus.publish([event])

    # Both receive it
    received1 = await asyncio.wait_for(queue1.get(), timeout=0.5)
    received2 = await asyncio.wait_for(queue2.get(), timeout=0.5)

    assert received1.event_type == EventType.STEP_STARTED
    assert received2.event_type == EventType.STEP_STARTED

    # Cleanup
    bus.unsubscribe(sub1)
    bus.unsubscribe(sub2)


@pytest.mark.asyncio
async def test_unsubscribe():
    """Unsubscribe stops event delivery."""
    bus = EventBus()

    queue = Queue()
    sub = bus.subscribe("run_1", queue)

    # Publish first event
    event1 = Event(
        event_type=EventType.RUN_STARTED,
        run_id="run_1",
        summary="Event 1",
    )
    await bus.publish([event1])

    # Receive it
    received = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert received.summary == "Event 1"

    # Unsubscribe
    bus.unsubscribe(sub)

    # Publish second event
    event2 = Event(
        event_type=EventType.STEP_STARTED,
        run_id="run_1",
        summary="Event 2",
    )
    await bus.publish([event2])

    # Should not receive it
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_publish_empty_list():
    """Publishing empty list is safe."""
    bus = EventBus()
    queue = Queue()
    sub = bus.subscribe("run_1", queue)

    await bus.publish([])

    # Queue remains empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)

    bus.unsubscribe(sub)


@pytest.mark.asyncio
async def test_publish_to_run():
    """publish_to_run() delivers to specific run only."""
    bus = EventBus()

    queue1 = Queue()
    queue2 = Queue()
    sub1 = bus.subscribe("run_1", queue1)
    sub2 = bus.subscribe("run_2", queue2)

    # Publish directly to run_1
    event = Event(
        event_type=EventType.TOOL_SUCCEEDED,
        run_id="run_1",
        step_id="step_1",
        summary="Tool done",
    )
    await bus.publish_to_run("run_1", event)

    # Only queue1 receives
    received = await asyncio.wait_for(queue1.get(), timeout=0.5)
    assert received.run_id == "run_1"

    # queue2 empty
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue2.get(), timeout=0.1)

    bus.unsubscribe(sub1)
    bus.unsubscribe(sub2)


@pytest.mark.asyncio
async def test_batch_publish():
    """Batch publish delivers all events."""
    bus = EventBus()
    queue = Queue()
    sub = bus.subscribe("run_1", queue)

    events = [
        Event(
            event_type=EventType.RUN_STARTED,
            run_id="run_1",
            summary="Event 1",
        ),
        Event(
            event_type=EventType.STEP_STARTED,
            run_id="run_1",
            step_id="step_1",
            summary="Event 2",
        ),
        Event(
            event_type=EventType.STEP_COMPLETED,
            run_id="run_1",
            step_id="step_1",
            summary="Event 3",
        ),
    ]

    await bus.publish(events)

    # Receive all three
    received = []
    for _ in range(3):
        evt = await asyncio.wait_for(queue.get(), timeout=0.5)
        received.append(evt)

    assert len(received) == 3
    assert received[0].summary == "Event 1"
    assert received[1].summary == "Event 2"
    assert received[2].summary == "Event 3"

    bus.unsubscribe(sub)
