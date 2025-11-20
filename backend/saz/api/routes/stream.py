"""WebSocket streaming endpoint for per-run events."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from saz.audit.event_bus import event_bus
from saz.domain.event_schema import Event

router = APIRouter()


@router.websocket("/api/v1/runs/{run_id}/stream")
async def stream_run_events(
    websocket: WebSocket,
    run_id: str,
):
    """
    Stream live events for a specific run via WebSocket.

    This endpoint provides real-time event streaming for a single run.
    Clients connect to this endpoint and receive events as they are emitted
    by the workflow engine.

    Args:
        websocket: WebSocket connection
        run_id: Run ID to stream events for

    Protocol:
        - Client connects
        - Server sends {"type": "connected"} acknowledgment
        - Server sends event objects as they occur
        - Server sends {"type": "ping"} every 30s for keepalive
        - Client can send any message as pong response

    Event Format:
        {
            "id": "evt_xxx",
            "event_type": "step.completed",
            "timestamp": "2025-11-20T10:30:45.123Z",
            "run_id": "run_abc123",
            "step_id": "step_xyz",
            "correlation_id": "corr_xxx",
            "planner_mode": "agentic",
            "severity": "info",
            "actor": "system",
            "summary": "Step completed successfully",
            "payload": {...},
            "tags": {...},
            "schema_version": 1
        }
    """
    await websocket.accept()

    # Subscribe to event bus for this run
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
    subscription = event_bus.subscribe(run_id, queue)

    try:
        # Send connection acknowledgment
        await websocket.send_json(
            {
                "type": "connected",
                "run_id": run_id,
                "message": f"Connected to event stream for run {run_id}",
            }
        )

        # Event streaming loop
        while True:
            try:
                # Wait for event with timeout for keepalive
                event: Event = await asyncio.wait_for(queue.get(), timeout=30.0)

                # Serialize and send event
                event_dict = {
                    "id": event.id,
                    "event_type": event.event_type.value,
                    "timestamp": event.timestamp.isoformat(),
                    "schema_version": event.schema_version,
                    "run_id": event.run_id,
                    "step_id": event.step_id,
                    "correlation_id": event.correlation_id,
                    "planner_mode": event.planner_mode,
                    "severity": event.severity,
                    "actor": event.actor,
                    "summary": event.summary,
                    "payload": event.payload,
                    "tags": event.tags,
                }

                await websocket.send_json(event_dict)

            except TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Log error but don't crash
        import logging

        logging.error(f"WebSocket error for run {run_id}: {e}")
    finally:
        # Unsubscribe from event bus
        event_bus.unsubscribe(subscription)
