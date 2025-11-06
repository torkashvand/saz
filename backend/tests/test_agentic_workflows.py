"""Integration tests for agentic workflow execution with tools, planning, and retries."""

import time


def test_ai_extract_workflow(app_client, event_collector):
    """Test AI extraction workflow with real AI ops."""
    dsl_yaml = """
flow:
  name: DataExtraction
workflow:
  steps:
    - id: extract_data
      type: ai.extract
      instruction: Extract structured data from input
      params:
        data:
          text: "John Doe, age 35, email john@example.com"
      expect:
        type: object
        properties:
          name:
            type: string
          age:
            type: number
          email:
            type: string
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    assert response.status_code == 200
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    assert response.status_code == 200
    run_id = response.json()["id"]

    time.sleep(3)

    # Check run completed
    response = app_client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    run_data = response.json()
    assert run_data["status"] == "completed"

    # Verify step output
    assert len(run_data["steps"]) == 1
    step = run_data["steps"][0]
    assert step["status"] == "completed"
    assert "output" in step


def test_http_request_workflow(app_client):
    """Test HTTP request tool in workflow."""
    dsl_yaml = """
flow:
  name: HttpTest
workflow:
  steps:
    - id: api_call
      type: tool.call
      tool: http_request
      params:
        method: GET
        url: "https://httpbin.org/get"
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(3)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"

    step = run_data["steps"][0]
    assert "output" in step
    assert step["output"]["status_code"] == 200


def test_artifact_storage_workflow(app_client):
    """Test artifact storage and retrieval."""
    dsl_yaml = """
flow:
  name: ArtifactTest
workflow:
  steps:
    - id: store_artifact
      type: artifact.store
      params:
        name: test_result
        content:
          key: value
          number: 42
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(2)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"

    step = run_data["steps"][0]
    assert "artifact_id" in step["output"]


def test_retry_with_exponential_backoff(app_client, monkeypatch):
    """Test retry logic with exponential backoff."""
    from saz.agents import ai_ops

    call_count = {"count": 0}

    original_run = ai_ops.AIOperationsRunner.run_ai_op

    async def mock_fail_twice(*args, **kwargs):
        call_count["count"] += 1
        if call_count["count"] <= 2:
            raise ConnectionError("Temporary failure")
        return await original_run(*args, **kwargs)

    monkeypatch.setattr(ai_ops.AIOperationsRunner, "run_ai_op", mock_fail_twice)

    dsl_yaml = """
flow:
  name: RetryTest
workflow:
  steps:
    - id: retry_step
      type: ai.extract
      instruction: Extract data
      params:
        data:
          text: "test"
      retry:
        attempts: 3
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(5)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    # Should succeed on 3rd attempt
    assert run_data["status"] == "completed"
    assert call_count["count"] == 3


def test_budget_tracking(app_client):
    """Test budget tracking and enforcement."""
    dsl_yaml = """
flow:
  name: BudgetTest
  budget:
    max_steps: 2
    max_cost_usd: 0.01
workflow:
  steps:
    - id: step1
      type: ai.extract
      instruction: Extract 1
    - id: step2
      type: ai.extract
      instruction: Extract 2
    - id: step3
      type: ai.extract
      instruction: Extract 3
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(4)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    # Should fail due to step budget
    assert run_data["status"] == "failed"
    assert "budget" in run_data["error"]["message"].lower()


def test_error_handling_continue(app_client, monkeypatch):
    """Test continue_on_fail error handling."""
    from saz.tools import http_tool

    async def mock_http_fail(*args, **kwargs):
        raise ConnectionError("Network error")

    monkeypatch.setattr(http_tool.HttpTool, "execute", mock_http_fail)

    dsl_yaml = """
flow:
  name: ContinueTest
workflow:
  steps:
    - id: fail_step
      type: tool.call
      tool: http_request
      params:
        method: GET
        url: "https://example.com"
      continue_on_fail: true
    - id: success_step
      type: artifact.store
      params:
        name: after_failure
        content:
          status: success
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(3)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    # Should complete despite first step failure
    assert run_data["status"] == "completed"
    assert len(run_data["steps"]) == 2
    assert run_data["steps"][0]["status"] == "failed"
    assert run_data["steps"][1]["status"] == "completed"


def test_template_variable_substitution(app_client):
    """Test template variable substitution in workflow."""
    dsl_yaml = """
flow:
  name: TemplateTest
workflow:
  steps:
    - id: extract_name
      type: ai.extract
      instruction: Extract name
      params:
        data:
          text: "{{ $form.input_text }}"
      expect:
        type: object
        properties:
          name:
            type: string
    - id: store_result
      type: artifact.store
      params:
        name: extracted_name
        content:
          extracted: "{{ $step('extract_name').output.name }}"
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post(
        "/api/v1/runs", json={"flow_id": flow_id, "payload": {"input_text": "My name is Alice"}}
    )
    run_id = response.json()["id"]
    time.sleep(3)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"


def test_conditional_branching(app_client):
    """Test conditional workflow branching."""
    dsl_yaml = """
flow:
  name: ConditionalTest
workflow:
  steps:
    - id: check_condition
      type: condition
      if: "{{ $form.approve }}"
    - id: approved_action
      type: artifact.store
      params:
        name: approval_result
        content:
          status: approved
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    # Test with approve=true
    response = app_client.post(
        "/api/v1/runs", json={"flow_id": flow_id, "payload": {"approve": True}}
    )
    run_id = response.json()["id"]
    time.sleep(2)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"


def test_step_result_persistence(app_client):
    """Test that step results are persisted and accessible."""
    dsl_yaml = """
flow:
  name: PersistenceTest
workflow:
  steps:
    - id: step1
      type: ai.extract
      instruction: Extract number
      params:
        data:
          value: 42
    - id: step2
      type: artifact.store
      params:
        name: final_result
        content:
          from_previous: "{{ $step('step1') }}"
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(3)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"

    # Verify both steps have outputs
    assert all("output" in step for step in run_data["steps"])


def test_event_broadcasting_for_agentic_run(app_client, event_collector):
    """Test that all events are broadcast during agentic execution."""
    dsl_yaml = """
flow:
  name: EventTest
workflow:
  steps:
    - id: step1
      type: ai.extract
      instruction: Extract
    - id: step2
      type: artifact.store
      params:
        name: result
        content:
          status: done
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    response.json()["id"]
    time.sleep(3)

    # Verify events
    event_types = [e.event_type for e in event_collector]
    assert "run.started" in event_types
    assert event_types.count("step.started") == 2
    assert event_types.count("step.completed") == 2
    assert "run.completed" in event_types

    # Verify event order
    assert event_types[0] == "run.started"
    assert event_types[1] == "step.started"
    assert event_types[-1] == "run.completed"


def test_no_silent_failures(app_client, monkeypatch):
    """Test that all errors are surfaced and broadcast."""
    from saz.agents import ai_ops

    async def mock_error(*args, **kwargs):
        raise ValueError("Intentional test error with details")

    monkeypatch.setattr(ai_ops.AIOperationsRunner, "run_ai_op", mock_error)

    dsl_yaml = """
flow:
  name: ErrorTest
workflow:
  steps:
    - id: fail_step
      type: ai.extract
      instruction: Extract
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(2)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()

    # Run should be failed, not silently stuck
    assert run_data["status"] == "failed"

    # Error should have full details
    assert "error" in run_data
    assert "message" in run_data["error"]
    assert "Intentional test error" in run_data["error"]["message"]
    assert "type" in run_data["error"]
    assert "traceback" in run_data["error"]

    # Step should also have error
    assert run_data["steps"][0]["status"] == "failed"
    assert "error" in run_data["steps"][0]


def test_multi_tool_workflow(app_client):
    """Test workflow using multiple different tools."""
    dsl_yaml = """
flow:
  name: MultiToolTest
workflow:
  steps:
    - id: extract_data
      type: ai.extract
      instruction: Extract info
      params:
        data:
          input: test
    - id: http_call
      type: tool.call
      tool: http_request
      params:
        method: GET
        url: "https://httpbin.org/uuid"
    - id: store_artifact
      type: artifact.store
      params:
        name: combined_result
        content:
          extracted: "{{ $step('extract_data').output }}"
          http_response: "{{ $step('http_call').status_code }}"
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(4)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"
    assert len(run_data["steps"]) == 3
    assert all(step["status"] == "completed" for step in run_data["steps"])


def test_plan_generation_with_rule_planner(app_client):
    """Test that rule planner generates correct execution plan."""
    dsl_yaml = """
flow:
  name: PlannerTest
workflow:
  steps:
    - id: step1
      type: ai.assess
      instruction: Assess input
      params:
        data:
          value: test
    - id: step2
      type: ai.generate
      instruction: Generate response
"""
    response = app_client.post("/api/v1/flows", json={"yaml": dsl_yaml})
    flow_id = response.json()["id"]

    response = app_client.post("/api/v1/runs", json={"flow_id": flow_id, "payload": {}})
    run_id = response.json()["id"]
    time.sleep(3)

    response = app_client.get(f"/api/v1/runs/{run_id}")
    run_data = response.json()
    assert run_data["status"] == "completed"

    # Both AI ops should have executed
    assert len(run_data["steps"]) == 2
