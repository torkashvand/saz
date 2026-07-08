"""WebSocket streaming endpoint for per-run events."""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status

from saz.audit.event_bus import event_bus
from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
from saz.domain.event_schema import Event
from saz.domain.literals import Role
from saz.security.tokens import TokenError, decode_stream_ticket

router = APIRouter()


@router.websocket("/api/v1/runs/{run_id}/stream")
async def stream_run_events(
    websocket: WebSocket,
    run_id: str,
    ticket: str | None = Query(default=None),
    uow: UnitOfWork = Depends(get_uow),
) -> None:
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
    # Authenticate before accepting the WebSocket. Browsers cannot set
    # Authorization headers on a WS upgrade, so authentication rides a query
    # parameter — which lands in proxy/server logs. That's why this endpoint
    # accepts only a SHORT-LIVED, run-scoped ticket (minted via
    # POST /runs/{id}/stream_ticket over the authed HTTP channel), never the
    # long-lived access token. Reject (close before accept) if missing/invalid
    # so an unauthenticated client never sees a single event.
    if not ticket:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        user_id = decode_stream_ticket(ticket, run_id)
    except TokenError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # The mint endpoint already verified ownership, but re-check against live
    # state: the user may have been disabled within the ticket's lifetime.
    # Close before accept so an unauthorized client never sees a single event
    # (and cannot distinguish "not found" from "forbidden").
    assert uow.users is not None
    user = uow.users.get(user_id)
    if user is None or not user.is_active:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    assert uow.runs is not None
    run = uow.runs.get(run_id)
    if run is None or (run.created_by_user_id != user.id and user.role != Role.ADMIN):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # Subscribe BEFORE reading the snapshot so no live event emitted during
    # the snapshot read is lost. The live stream may then re-deliver an event
    # already in the snapshot; clients dedupe by event id.
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
    subscription = event_bus.subscribe(run_id, queue)

    def _serialize(event: Any) -> dict:
        # Live events (domain Event) carry an EventType enum; snapshot rows
        # (DB Event) carry a plain string. Normalize to the wire string.
        event_type = event.event_type
        event_type_str = event_type.value if hasattr(event_type, "value") else event_type
        # severity is a Severity StrEnum on live domain events and a plain
        # string on snapshot DB rows — normalize to the wire string so the WS
        # shape matches the REST EventResponse (which marks severity required).
        severity = event.severity
        severity_str = severity.value if hasattr(severity, "value") else severity
        return {
            "id": event.id,
            "event_type": event_type_str,
            "timestamp": event.timestamp.isoformat(),
            "schema_version": event.schema_version,
            "seq": getattr(event, "seq", None),
            "run_id": event.run_id,
            "step_id": event.step_id,
            "correlation_id": event.correlation_id,
            "planner_mode": event.planner_mode,
            "severity": severity_str,
            # actor_user_id (a raw user id) is intentionally not sent on the
            # wire; the actor *role* is enough for the client to attribute.
            "actor": event.actor,
            "summary": event.summary,
            "payload": event.payload,
            "tags": event.tags,
        }

    try:
        # Send connection acknowledgment
        await websocket.send_json(
            {
                "type": "connected",
                "run_id": run_id,
                "message": f"Connected to event stream for run {run_id}",
            }
        )

        # Replay persisted events so a client connecting mid-run (or after a
        # sweeper timeout, which is not broadcast live) sees canonical state
        # instead of only events emitted after connect.
        assert uow.event_queries is not None
        snapshot, _ = uow.event_queries.get_by_run(run_id=run_id, limit=500)
        for past in snapshot:
            await websocket.send_json({**_serialize(past), "snapshot": True})
        await websocket.send_json({"type": "snapshot_complete", "run_id": run_id})

        # Live event streaming loop
        while True:
            try:
                # Wait for event with timeout for keepalive
                event: Event = await asyncio.wait_for(queue.get(), timeout=30.0)
                # If the bus had to drop events for this slow consumer, tell the
                # client to treat REST/DB as canonical and refetch the timeline.
                if subscription.dropped:
                    subscription.dropped = False
                    await websocket.send_json(
                        {
                            "type": "gap",
                            "run_id": run_id,
                            "message": "events dropped; refetch run events via REST",
                        }
                    )
                await websocket.send_json(_serialize(event))

            except TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Log error but don't crash
        logging.error(f"WebSocket error for run {run_id}: {e}")
    finally:
        # Unsubscribe from event bus
        event_bus.unsubscribe(subscription)
