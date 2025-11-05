"""Unit tests for workflow engine - Process state transitions and execution."""
import pytest
from saz.engine.workflow import (
    Process,
    Success,
    Failed,
    Suspend,
    Waiting,
    Complete,
    Skipped,
    ProcessStatus,
    StepStatus,
    step,
    inputstep,
    StepList
)


def test_success_state():
    """Test Success process state."""
    state = {"data": "test"}
    proc = Success(state)

    assert proc.issuccess() is True
    assert proc.isfailed() is False
    assert proc.issuspend() is False
    assert proc.iswaiting() is False
    assert proc.iscomplete() is False
    assert proc.isskipped() is False

    assert proc.status == StepStatus.SUCCESS
    assert proc.overall_status == ProcessStatus.RUNNING
    assert proc.unwrap() == state


def test_failed_state():
    """Test Failed process state."""
    error_state = {"error": "Something went wrong"}
    proc = Failed(error_state)

    assert proc.isfailed() is True
    assert proc.issuccess() is False
    assert proc.status == StepStatus.FAILED
    assert proc.overall_status == ProcessStatus.FAILED
    assert proc.unwrap() == error_state


def test_suspend_state():
    """Test Suspend process state (awaiting human input)."""
    state = {"pending": True}
    proc = Suspend(state)

    assert proc.issuspend() is True
    assert proc.issuccess() is False
    assert proc.status == StepStatus.SUSPEND
    assert proc.overall_status == ProcessStatus.SUSPENDED


def test_waiting_state():
    """Test Waiting process state (webhook callback)."""
    state = {"waiting_for": "webhook"}
    proc = Waiting(state)

    assert proc.iswaiting() is True
    assert proc.issuccess() is False
    assert proc.status == StepStatus.WAITING
    assert proc.overall_status == ProcessStatus.WAITING


def test_complete_state():
    """Test Complete process state."""
    final_state = {"completed": True}
    proc = Complete(final_state)

    assert proc.iscomplete() is True
    assert proc.issuccess() is False
    assert proc.status == StepStatus.COMPLETE
    assert proc.overall_status == ProcessStatus.COMPLETED


def test_skipped_state():
    """Test Skipped process state."""
    state = {"skipped": True}
    proc = Skipped(state)

    assert proc.isskipped() is True
    assert proc.issuccess() is False
    assert proc.status == StepStatus.SKIPPED
    assert proc.overall_status == ProcessStatus.RUNNING


def test_process_map():
    """Test Process.map() applies function to state."""
    initial_state = {"count": 1}
    proc = Success(initial_state)

    def increment(state):
        return {**state, "count": state["count"] + 1}

    new_proc = proc.map(increment)

    assert new_proc.unwrap()["count"] == 2
    assert new_proc.issuccess() is True


def test_process_execute_step_on_success():
    """Test executing step on Success state continues."""
    initial_state = {"value": 1}
    proc = Success(initial_state)

    def test_step(state):
        return Success({**state, "value": state["value"] * 2})

    result = proc.execute_step(test_step)

    assert result.issuccess() is True
    assert result.unwrap()["value"] == 2


def test_process_execute_step_on_suspend():
    """Test executing step on Suspend state preserves suspension."""
    state = {"suspended": True}
    proc = Suspend(state)

    def should_not_run(state):
        return Success({"should_not": "run"})

    result = proc.execute_step(should_not_run)

    # Should remain suspended
    assert result.issuspend() is True
    assert result.unwrap() == state


def test_process_execute_step_on_failed():
    """Test executing step on Failed state preserves failure."""
    error_state = {"error": "failed"}
    proc = Failed(error_state)

    def should_not_run(state):
        return Success({})

    result = proc.execute_step(should_not_run)

    assert result.isfailed() is True
    assert result.unwrap() == error_state


def test_step_decorator_success():
    """Test @step decorator for successful execution."""
    @step(name="test_step")
    def my_step(state):
        return {**state, "processed": True}

    initial_state = {"input": "data"}
    result = my_step(initial_state)

    assert result.issuccess() is True
    assert result.unwrap()["processed"] is True
    assert result.unwrap()["input"] == "data"
    assert my_step.name == "test_step"


def test_step_decorator_exception_handling():
    """Test @step decorator catches exceptions and returns Failed."""
    @step(name="failing_step")
    def failing_step(state):
        raise ValueError("Test error")

    result = failing_step({"input": "data"})

    assert result.isfailed() is True
    assert "error" in result.unwrap()


def test_inputstep_decorator():
    """Test @inputstep decorator returns Suspend."""
    @inputstep(name="user_input")
    def my_input(state):
        # This function body won't be called
        pass

    state = {"waiting": True}
    result = my_input(state)

    assert result.issuspend() is True
    assert result.unwrap() == state
    assert my_input.name == "user_input"


def test_steplist_composition():
    """Test StepList composition with >> operator."""
    @step(name="step1")
    def step1(state):
        return {**state, "step1": True}

    @step(name="step2")
    def step2(state):
        return {**state, "step2": True}

    steps = StepList([step1]) >> step2

    assert len(steps) == 2
    assert steps[0].name == "step1"
    assert steps[1].name == "step2"


def test_steplist_merge():
    """Test merging two StepLists."""
    @step(name="step1")
    def step1(state):
        return state

    @step(name="step2")
    def step2(state):
        return state

    @step(name="step3")
    def step3(state):
        return state

    list1 = StepList([step1, step2])
    list2 = StepList([step3])

    merged = list1 >> list2

    assert len(merged) == 3
    assert merged[0].name == "step1"
    assert merged[2].name == "step3"


def test_process_fold():
    """Test Process._fold internal method."""
    success_proc = Success({"data": 1})

    # Test fold returns correct handler result
    result = success_proc._fold(
        success=lambda s: "success_handler",
        skipped=lambda s: "skipped_handler",
        suspend=lambda s: "suspend_handler",
        waiting=lambda s: "waiting_handler",
        failed=lambda s: "failed_handler",
        complete=lambda s: "complete_handler"
    )

    assert result == "success_handler"


def test_process_repr():
    """Test Process string representation."""
    proc = Success({"test": "data"})
    repr_str = repr(proc)

    assert "Success" in repr_str
    assert "test" in repr_str


def test_step_chaining():
    """Test chaining multiple steps together."""
    @step(name="add_one")
    def add_one(state):
        return {"value": state["value"] + 1}

    @step(name="multiply_two")
    def multiply_two(state):
        return {"value": state["value"] * 2}

    initial = Success({"value": 5})

    # Execute steps in sequence
    result1 = initial.execute_step(add_one)
    result2 = result1.execute_step(multiply_two)

    assert result2.issuccess() is True
    assert result2.unwrap()["value"] == 12  # (5 + 1) * 2


def test_process_status_enum():
    """Test ProcessStatus enum values."""
    assert ProcessStatus.CREATED == "created"
    assert ProcessStatus.RUNNING == "running"
    assert ProcessStatus.SUSPENDED == "suspended"
    assert ProcessStatus.WAITING == "waiting"
    assert ProcessStatus.FAILED == "failed"
    assert ProcessStatus.COMPLETED == "completed"


def test_step_status_enum():
    """Test StepStatus enum values."""
    assert StepStatus.SUCCESS == "success"
    assert StepStatus.SKIPPED == "skipped"
    assert StepStatus.SUSPEND == "suspend"
    assert StepStatus.WAITING == "waiting"
    assert StepStatus.FAILED == "failed"
    assert StepStatus.COMPLETE == "complete"
