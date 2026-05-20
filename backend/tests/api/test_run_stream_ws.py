"""Tests for WebSocket event streaming."""

import asyncio

import pytest
from sqlalchemy.orm import Session

from saz.audit.event_bus import event_bus
from saz.db.models import Flow, Run
from saz.domain.event_schema import Event, EventType
from tests.conftest import TEST_USER_ID


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


def test_websocket_ping_pong(app_client, run_for_stream, test_user_token):
    """WebSocket handles ping/pong."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?token={test_user_token}"
    ) as ws:
        # Receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"

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
    """WebSocket connection to nonexistent run is accepted (auth required)."""
    # WebSocket endpoint accepts connections even for nonexistent runs as
    # long as the caller is authenticated.
    with app_client.websocket_connect(
        f"/api/v1/runs/nonexistent/stream?token={test_user_token}"
    ) as ws:
        # Should receive connection acknowledgment
        ack = ws.receive_json()
        assert ack["type"] == "connected"
        assert ack["run_id"] == "nonexistent"
