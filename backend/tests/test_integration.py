"""Integration tests for ThreadPoolExecutor execution + WebSocket events."""

import time


def test_register_and_list_flows(app_client):
    """Test flow registration and listing."""
    dsl_yaml = """
flow:
  name: UserOnboarding
  version: "1.0"
  description: "User onboarding workflow"
form:
  fields:
    - name: username
      type: text
      required: true
    - name: email
      type: text
      required: true
workflow:
  steps:
    - id: step1
      type: ai.extract
      instruction: "Extract user info"
"""

    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["name"] == "UserOnboarding"
    flow_id = data["id"]

    response = app_client.get("/api/v1/flows")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "UserOnboarding"

    response = app_client.get(f"/api/v1/flows/{flow_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "UserOnboarding"
    assert data["version"] == "1.0"


def test_create_run_triggers_execution_and_finishes(app_client, event_collector):
    """Test that POST /api/v1/runs immediately schedules and executes."""
    # Register flow
    dsl_yaml = """
flow:
  name: SimpleFlow
workflow:
  steps:
    - id: extract_step
      type: ai.extract
      instruction: "Extract data"
    - id: transform_step
      type: data.transform
      transform: {"key": "value"}
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    assert response.status_code == 200
    flow_id = response.json()["id"]

    # Create run
    response = app_client.post(
        "/api/v1/runs", json={"flow_id": flow_id, "payload": {"data": "test"}}
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["status"] == "running"
    run_id = data["id"]

    # Wait for execution to complete (single-thread executor)
    time.sleep(2)

    # Check run status
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    run_data = response.json()
    assert run_data["status"] == "completed"
    assert len(run_data["steps"]) == 2

    # Verify events
    event_types = [e.event_type for e in event_collector]
    assert "run.started" in event_types
    assert "step.started" in event_types
    assert "step.completed" in event_types
    assert "run.completed" in event_types


def test_event_sequence_per_step(app_client, event_collector):
    """Test exact event ordering."""
    dsl_yaml = """
flow:
  name: EventFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    response.json()["id"]

    time.sleep(1.5)

    event_types = [e.event_type for e in event_collector]
    # Expected: run.started, step.started, step.completed, run.completed
    assert event_types[0] == "run.started"
    assert event_types[1] == "step.started"
    assert event_types[2] == "step.completed"
    assert event_types[3] == "run.completed"


def test_step_failed_emits_error_payload(app_client, event_collector, monkeypatch):
    """Test step failure with error details."""
    from saz.engine import executor

    # Mock step execution to always fail
    async def mock_fail(*args, **kwargs):
        raise ValueError("Test error for step failure")

    monkeypatch.setattr(executor.WorkflowExecutor, "_execute_ai_extract", mock_fail)

    dsl_yaml = """
flow:
  name: FailFlow
workflow:
  steps:
    - id: fail_step
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]

    time.sleep(1.5)

    # Check run failed
    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "failed"
    assert run_data["error"] is not None
    assert "message" in run_data["error"]
    assert "type" in run_data["error"]
    assert "traceback" in run_data["error"]

    # Check step failed event
    failed_events = [e for e in event_collector if e.event_type == "step.failed"]
    assert len(failed_events) > 0
    step_failed = failed_events[0]
    assert "error" in step_failed.data
    assert step_failed.data["error"]["type"] == "ValueError"
    assert "Test error for step failure" in step_failed.data["error"]["message"]


def test_retry_creates_new_run_from_failed_step(app_client, monkeypatch):
    """Test retry after failure."""
    from saz.engine import executor

    call_count = {"count": 0}

    async def mock_fail_once(*args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise ValueError("First attempt fails")
        return {"extracted": "success"}

    monkeypatch.setattr(executor.WorkflowExecutor, "_execute_ai_extract", mock_fail_once)

    dsl_yaml = """
flow:
  name: RetryFlow
workflow:
  steps:
    - id: retry_step
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    first_run_id = response.json()["id"]
    time.sleep(1.5)

    # Verify first run failed
    response = app_client.get(f"/api/v1/runs/{first_run_id}")
    assert response.json()["status"] == "failed"

    # Retry
    response = app_client.post(f"/api/v1/runs/{first_run_id}/retry")
    assert response.status_code == 200
    second_run_id = response.json()["new_run_id"]
    assert second_run_id != first_run_id
    time.sleep(1.5)

    # Verify second run succeeded
    response = app_client.get(f"/api/v1/runs/{second_run_id}")
    assert response.json()["status"] == "completed"


def test_replay_from_step_n(app_client):
    """Test replay from specific step."""
    dsl_yaml = """
flow:
  name: ReplayFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
    - id: step2
      type: ai.generate
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    original_run_id = response.json()["id"]
    time.sleep(2)

    # Replay from step 1
    response = app_client.post(f"/api/v1/runs/{original_run_id}/replay?from_step=1")
    assert response.status_code == 200
    replay_run_id = response.json()["new_run_id"]
    assert replay_run_id != original_run_id
    time.sleep(2)

    response = app_client.get(f"/api/v1/runs/{replay_run_id}")
    assert response.json()["status"] == "completed"


def test_ws_events_streams_live_updates(app_client):
    """Test WebSocket /ws/events endpoint."""
    with app_client.websocket_connect("/ws/events") as websocket:
        # Receive connection ack
        data = websocket.receive_json()
        assert data["type"] == "system.connected"

        # Send ping
        websocket.send_text("ping")
        data = websocket.receive_json()
        assert data["type"] == "system.pong"


def test_ws_backpressure_and_disconnect(app_client):
    """Test WebSocket handles disconnect gracefully."""
    with app_client.websocket_connect("/ws/events") as websocket:
        data = websocket.receive_json()
        assert data["type"] == "system.connected"
        # Abrupt close should not crash server


def test_error_envelope_on_not_found(app_client):
    """Test error envelope format."""
    response = app_client.get("/api/v1/runs/nonexistent-id")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert data["error"] == "NotFoundError"


def test_credentials_crud(app_client):
    """Test credential CRUD operations."""
    # Create
    response = app_client.post(
        "/api/v1/credentials",
        json={
            "name": "test_key",
            "credential_type": "api_token",
            "data": {"token": "secret123"},
            "description": "Test",
        },
    )
    assert response.status_code == 200

    # List (should not expose secret)
    response = app_client.get("/api/v1/credentials")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    # Data field should not be present in list
    assert "data" not in items[0]

    # Update
    response = app_client.put("/api/v1/credentials/test_key", json={"data": {"token": "newsecret"}})
    assert response.status_code == 200

    # Delete
    response = app_client.delete("/api/v1/credentials/test_key")
    assert response.status_code == 200


def test_flow_graph_endpoint(app_client):
    """Test flow graph endpoint returns schema-conformant payload."""
    dsl_yaml = """
flow:
  name: GraphFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
    - id: step2
      type: ai.generate
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.get(f"/api/v1/flows/{flow_id}/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 2


def test_run_graph_endpoint(app_client):
    """Test run graph endpoint."""
    dsl_yaml = """
flow:
  name: RunGraphFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(1.5)

    response = app_client.get(f"/api/v1/runs/{run_id}/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert "status_by_step" in data


def test_concurrent_runs(app_client):
    """Test multiple concurrent runs execute correctly."""
    dsl_yaml = """
flow:
  name: ConcurrentFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    # Create 3 runs
    run_ids = []
    for i in range(3):
        response = app_client.post(
            "/api/v1/runs", json={"flow_id": flow_id, "payload": {"index": i}}
        )
        assert response.status_code == 200
        run_ids.append(response.json()["id"])

    time.sleep(3)

    # All should complete
    for run_id in run_ids:
        response = app_client.get(f"/api/v1/runs/{run_id}")
        assert response.json()["status"] == "completed"


def test_no_duplicate_execution(app_client):
    """Test that same run cannot be scheduled twice."""
    dsl_yaml = """
flow:
  name: DuplicateFlow
workflow:
  steps:
    - id: step1
      type: ai.extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    assert response.status_code == 200
    run_id = response.json()["id"]

    # Try to create same run again should fail with 409
    # (In practice this won't happen via API, but scheduler should prevent it)
    from saz.engine.scheduler import get_scheduler

    scheduler = get_scheduler()

    # Second schedule should return False
    result = scheduler.schedule(run_id)
    assert result is False
