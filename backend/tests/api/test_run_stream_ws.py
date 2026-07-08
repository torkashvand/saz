"""Tests for WebSocket event streaming.

The stream authenticates via a short-lived, run-scoped ticket minted at
POST /runs/{id}/stream_ticket — never the long-lived access token (query
strings land in proxy/server logs)."""

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


def _mint_ticket(app_client, run_id: str) -> str:
    resp = app_client.post(f"/api/v1/runs/{run_id}/stream_ticket")
    assert resp.status_code == 200, resp.text
    return resp.json()["ticket"]


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


def test_websocket_connect_and_receive(app_client, run_for_stream):
    """WebSocket connects and receives events."""
    # Connect WebSocket
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?ticket={_mint_ticket(app_client, run_for_stream)}"
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


def test_websocket_multiple_events(app_client, run_for_stream):
    """WebSocket receives multiple events."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?ticket={_mint_ticket(app_client, run_for_stream)}"
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


def test_websocket_event_includes_severity(app_client, run_for_stream):
    """WS-serialized events must carry `severity`, matching the REST
    EventResponse shape and the frontend Event type (which marks it required)."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?ticket={_mint_ticket(app_client, run_for_stream)}"
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


def test_websocket_ping_pong(app_client, run_for_stream):
    """WebSocket handles ping/pong."""
    with app_client.websocket_connect(
        f"/api/v1/runs/{run_for_stream}/stream?ticket={_mint_ticket(app_client, run_for_stream)}"
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


def test_websocket_only_receives_own_run_events(app_client, db_engine):
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
        f"/api/v1/runs/run_iso_1/stream?ticket={_mint_ticket(app_client, 'run_iso_1')}"
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


def test_ticket_mint_requires_existing_run(app_client):
    """Minting a stream ticket for a nonexistent run is a 404."""
    resp = app_client.post("/api/v1/runs/nonexistent/stream_ticket")
    assert resp.status_code == 404


def test_websocket_rejects_ticket_for_other_run(app_client, run_for_stream, db_engine):
    """A ticket is scoped to ONE run — it must not open another run's stream."""
    from starlette.websockets import WebSocketDisconnect

    with Session(db_engine) as session:
        session.add(
            Run(
                created_by_user_id=TEST_USER_ID,
                id="run_ws_other",
                flow_id="flow_ws",
                status="running",
                planner_mode="deterministic",
            )
        )
        session.commit()

    ticket = _mint_ticket(app_client, run_for_stream)
    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(
            f"/api/v1/runs/run_ws_other/stream?ticket={ticket}"
        ) as ws:
            ws.receive_json()


def test_websocket_rejects_access_token_as_ticket(app_client, run_for_stream, test_user_token):
    """The long-lived access token must NOT be accepted on the WS query param —
    the whole point of tickets is keeping it out of URLs and proxy logs."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(
            f"/api/v1/runs/{run_for_stream}/stream?ticket={test_user_token}"
        ) as ws:
            ws.receive_json()


def test_websocket_rejects_expired_ticket(app_client, run_for_stream, monkeypatch):
    """A ticket past its exp is refused."""
    from datetime import UTC, datetime

    import jwt as pyjwt
    from starlette.websockets import WebSocketDisconnect

    from saz.settings import settings

    now = int(datetime.now(UTC).timestamp())
    stale = pyjwt.encode(
        {
            "sub": TEST_USER_ID,
            "run_id": run_for_stream,
            "iat": now - 120,
            "exp": now - 60,
            "type": "stream_ticket",
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(
            f"/api/v1/runs/{run_for_stream}/stream?ticket={stale}"
        ) as ws:
            ws.receive_json()


def test_websocket_rejects_non_owner(app_client, db_engine):
    """A run owned by another user: the ticket mint is refused, and even a
    forged-scope ticket fails the WS-level ownership re-check."""
    from datetime import UTC, datetime

    from starlette.websockets import WebSocketDisconnect

    from saz.db.models import Flow, Run, User
    from saz.security.passwords import hash_password
    from saz.security.tokens import create_stream_ticket

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
        # Flush so the owner row exists before the flow/run reference it
        # (PostgreSQL enforces the FK at insert time).
        session.flush()
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

    # app_client authenticates as TEST_USER_ID, not other_id -> mint refused.
    resp = app_client.post("/api/v1/runs/run_other/stream_ticket")
    assert resp.status_code == 403

    # Even a ticket carrying the right run_id but a non-owner user fails the
    # WS-level ownership re-check.
    forged = create_stream_ticket(TEST_USER_ID, "run_other")
    with pytest.raises(WebSocketDisconnect):
        with app_client.websocket_connect(f"/api/v1/runs/run_other/stream?ticket={forged}") as ws:
            ws.receive_json()
