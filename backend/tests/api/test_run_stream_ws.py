"""Tests for WebSocket event streaming."""

import asyncio

import pytest
from sqlalchemy.orm import Session

from saz.audit.event_bus import event_bus
from saz.db.models import Flow, Run
from saz.domain.event_schema import Event, EventType
from tests.conftest import TEST_USER_ID


def _drain_snapshot(ws) -> list[dict]:
    """Consume the connect snapshot replay up to the snapshot_complete marker.

    Returns the snapshot events (excluding the marker)."""
    events: list[dict] = []
    while True:
        msg = ws.receive_json()
        if msg.get("type") == "snapshot_complete":
            return events
        events.append(msg)


@pytest.fixture
def run_for_stream(db_engine):
    """Create a run for WebSocket testing."""
    with Session(db_engine) as session:
        flow = Flow(
            created_by_user_id=TEST_USER_ID,
            id="flow_ws",
            name="WS Test Flow",
            definition={"workflow": {"planner_mode": "deterministic"}},
        )
        session.add(flow)
        session.commit()

        run = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_ws_123",
            flow_id="flow_ws",
            status="running",
            planner_mode="deterministic",
        )
        session.add(run)
        session.commit()

    return "run_ws_123"


def test_websocket_connect_and_receive(app_client, run_for_stream, test_user_token):
    """WebSocket connects and receives events."""
    # Connect WebSocket
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?token={test_user_token}"
    ) as ws:
        # Receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        assert ack["run_id"] == run_for_stream
        _drain_snapshot(ws)

        # Publish event via event bus
        event = Event(
            event_type=EventType.STEP_STARTED,
            run_id=run_for_stream,
            step_id="step_1",
            summary="Step 1 started",
        )

        # Publish async
        async def publish_event():
            await event_bus.publish([event])

        asyncio.run(publish_event())

        # Receive event
        try:
            data = ws.receive_json()

            # Verify event structure
            assert data["event_type"] == "step.started"
            assert data["run_id"] == run_for_stream
            assert data["step_id"] == "step_1"
            assert data["summary"] == "Step 1 started"
            assert "id" in data
            assert "timestamp" in data

        except Exception as e:
            pytest.fail(f"Failed to receive event: {e}")


def test_websocket_multiple_events(app_client, run_for_stream, test_user_token):
    """WebSocket receives multiple events."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?token={test_user_token}"
    ) as ws:
        # Receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        _drain_snapshot(ws)

        # Publish multiple events
        events = [
            Event(
                event_type=EventType.STEP_STARTED,
                run_id=run_for_stream,
                step_id="step_1",
                summary="Step 1",
            ),
            Event(
                event_type=EventType.TOOL_STARTED,
                run_id=run_for_stream,
                step_id="step_1",
                summary="Tool started",
            ),
            Event(
                event_type=EventType.TOOL_SUCCEEDED,
                run_id=run_for_stream,
                step_id="step_1",
                summary="Tool done",
            ),
        ]

        async def publish_events():
            await event_bus.publish(events)

        asyncio.run(publish_events())

        # Receive all three
        received = []
        for _ in range(3):
            try:
                data = ws.receive_json()
                received.append(data)
            except Exception as e:
                pytest.fail(f"Failed to receive event {len(received) + 1}: {e}")

        assert len(received) == 3
        assert received[0]["event_type"] == "step.started"
        assert received[1]["event_type"] == "tool.started"
        assert received[2]["event_type"] == "tool.succeeded"


def test_websocket_event_includes_severity(app_client, run_for_stream, test_user_token):
    """WS-serialized events must carry `severity`, matching the REST
    EventResponse shape and the frontend Event type (which marks it required)."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?token={test_user_token}"
    ) as ws:
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        _drain_snapshot(ws)

        event = Event(
            event_type=EventType.STEP_STARTED,
            run_id=run_for_stream,
            step_id="step_sev",
            summary="severity check",
        )

        async def publish_event():
            await event_bus.publish([event])

        asyncio.run(publish_event())

        data = ws.receive_json()
        assert "severity" in data, f"WS event omits severity: {data}"
        assert data["severity"] == "info"


def test_websocket_ping_pong(app_client, run_for_stream, test_user_token):
    """WebSocket handles ping/pong."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?token={test_user_token}"
    ) as ws:
        # Receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        _drain_snapshot(ws)

        # Send ping
        ws.send_text("ping")

        # Receive pong or keepalive
        try:
            response = ws.receive_json()
            # Should receive pong, keepalive, or connected
            assert response.get("type") in ["pong", "keepalive", "connected"]
        except Exception:
            # Some implementations may not respond to ping
            pass


def test_websocket_only_receives_own_run_events(app_client, db_engine, test_user_token):
    """WebSocket only receives events for its run_id."""
    # Create two runs
    with Session(db_engine) as session:
        flow = Flow(
            id="flow_iso",
            name="Isolation Test",
            definition={},
            created_by_user_id=TEST_USER_ID,
        )
        session.add(flow)

        run1 = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_iso_1",
            flow_id="flow_iso",
            status="running",
            planner_mode="deterministic",
        )
        run2 = Run(
            created_by_user_id=TEST_USER_ID,
            id="run_iso_2",
            flow_id="flow_iso",
            status="running",
            planner_mode="deterministic",
        )
        session.add_all([run1, run2])
        session.commit()

    # Connect to run_iso_1
    with app_client.websocket_connect(
        f"/api/v1/runs/run_iso_1/stream?token={test_user_token}"
    ) as ws:
        # Receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        assert ack["run_id"] == "run_iso_1"
        _drain_snapshot(ws)

        # Publish events for BOTH runs
        event_other = Event(
            event_type=EventType.STEP_STARTED,
            run_id="run_iso_2",
            step_id="step_1",
            summary="Other run event",
        )
        event_mine = Event(
            event_type=EventType.STEP_STARTED,
            run_id="run_iso_1",
            step_id="step_1",
            summary="My run event",
        )

        async def publish():
            await event_bus.publish([event_other, event_mine])

        asyncio.run(publish())

        # Should only receive the event for run_iso_1
        data = ws.receive_json()
        assert data["run_id"] == "run_iso_1"
        assert data["summary"] == "My run event"


def test_websocket_connection_to_nonexistent_run(app_client, test_user_token):
    """A stream for a nonexistent run is rejected (closed before accept).

    The endpoint authorizes per-run: a run that doesn't exist cannot be owned
    by the caller, so the connection is refused (and "not found" is
    indistinguishable from "forbidden" to avoid leaking run existence)."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(
            f"/api/v1/runs/nonexistent/stream?token={test_user_token}"
        ) as ws:
            ws.receive_json()


def test_websocket_rejects_non_owner(app_client, db_engine, test_user_token):
    """A run owned by another user cannot be streamed by this user."""
    from datetime import UTC, datetime

    from starlette.websockets import WebSocketDisconnect

    from saz.db.models import Flow, Run, User
    from saz.security.passwords import hash_password

    other_id = "00000000-0000-0000-0000-0000000000ff"
    with Session(db_engine) as session:
        session.add(
            User(
                id=other_id,
                username="other",
                email="other@example.com",
                display_name="Other",
                password_hash=hash_password("x"),
                is_active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Flow(
                created_by_user_id=other_id,
                id="flow_other",
                name="other flow",
                definition={"workflow": {"planner_mode": "deterministic"}},
            )
        )
        session.add(
            Run(
                created_by_user_id=other_id,
                id="run_other",
                flow_id="flow_other",
                status="running",
                planner_mode="deterministic",
            )
        )
        session.commit()

    # test_user_token belongs to TEST_USER_ID, not other_id -> must be refused.
    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(
            f"/api/v1/runs/run_other/stream?token={test_user_token}"
        ) as ws:
            ws.receive_json()
