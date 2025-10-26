"""Simplified workflow engine (vendored from orchestrator-core, domain concepts removed)."""
from __future__ import annotations

import functools
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, NoReturn, Protocol, TypeVar, cast, runtime_checkable
from uuid import UUID

import structlog

logger = structlog.get_logger(__name__)

State = dict[str, Any]
StepFunc = Callable[[State], "Process"]


class ProcessStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUSPENDED = "suspended"
    WAITING = "waiting"
    FAILED = "failed"
    COMPLETED = "completed"


class StepStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    SUSPEND = "suspend"
    WAITING = "waiting"
    FAILED = "failed"
    COMPLETE = "complete"


S = TypeVar("S")
F = TypeVar("F")


class Process(Generic[S]):
    """Process state wrapper (Success/Failed/Suspend/Complete/Waiting)."""

    def __init__(self, s: S):
        self.s = s

    def map(self, f: Callable[[S], S]) -> Process[S]:
        """Apply function to wrapped state."""

        def g(x: S) -> Process[S]:
            return self.__class__(f(x))

        return self._fold(g, g, g, g, g, g)

    def _fold(
        self,
        success: Callable[[S], F],
        skipped: Callable[[S], F],
        suspend: Callable[[S], F],
        waiting: Callable[[S], F],
        failed: Callable[[S], F],
        complete: Callable[[S], F],
    ) -> F:
        raise NotImplementedError("Must be implemented by subclass")

    def unwrap(self) -> S:
        return self._fold(
            lambda x: x,
            lambda x: x,
            lambda x: x,
            lambda x: x,
            lambda x: x,
            lambda x: x,
        )

    def issuccess(self) -> bool:
        return self._fold(
            lambda _: True,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
        )

    def isskipped(self) -> bool:
        return self._fold(
            lambda _: False,
            lambda _: True,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
        )

    def issuspend(self) -> bool:
        return self._fold(
            lambda _: False,
            lambda _: False,
            lambda _: True,
            lambda _: False,
            lambda _: False,
            lambda _: False,
        )

    def iswaiting(self) -> bool:
        return self._fold(
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: True,
            lambda _: False,
            lambda _: False,
        )

    def isfailed(self) -> bool:
        return self._fold(
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: True,
            lambda _: False,
        )

    def iscomplete(self) -> bool:
        return self._fold(
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: False,
            lambda _: True,
        )

    @property
    def status(self) -> StepStatus:
        return StepStatus[self.__class__.__name__.upper()]

    @property
    def overall_status(self) -> ProcessStatus:
        return self._fold(
            lambda _: ProcessStatus.RUNNING,
            lambda _: ProcessStatus.RUNNING,
            lambda _: ProcessStatus.SUSPENDED,
            lambda _: ProcessStatus.WAITING,
            lambda _: ProcessStatus.FAILED,
            lambda _: ProcessStatus.COMPLETED,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__} {self.s!r}"

    def execute_step(self, step: Callable[[S], Process[S]]) -> Process[S]:
        """Execute step if current state allows it."""
        return self._fold(step, step, Suspend, Waiting, Failed, Complete)


class Success(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return success(self.s)


class Skipped(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return skipped(self.s)


class Suspend(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return suspend(self.s)


class Waiting(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return waiting(self.s)


class Failed(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return failed(self.s)


class Complete(Process[S]):
    def _fold(self, success, skipped, suspend, waiting, failed, complete):
        return complete(self.s)


@runtime_checkable
class Step(Protocol):
    __name__: str
    name: str
    form: Callable[[State], Any] | None

    def __call__(self, state: State) -> Process: ...


@runtime_checkable
class Workflow(Protocol):
    __name__: str
    name: str
    description: str
    initial_input_form: Callable[[State], Any] | None
    steps: "StepList"

    def __call__(self) -> NoReturn: ...


def make_step_function(
    f: Callable,
    name: str,
    form: Callable[[State], Any] | None = None,
) -> Step:
    step_func = cast(Step, f)
    step_func.name = name
    step_func.form = form
    return step_func


class StepList(list[Step]):
    """List of workflow steps."""

    def __rshift__(self, other: "StepList | Step") -> "StepList":
        if isinstance(other, Step):
            return StepList([*self, other])
        if isinstance(other, StepList):
            return StepList([*self, *other])
        raise ValueError(f"Expected Step or StepList, got {type(other)}")

    def __str__(self) -> str:
        return f"StepList [{', '.join(x.name for x in self)}]"


def make_workflow(
    f: Callable,
    description: str,
    initial_input_form: Callable[[State], Any] | None,
    steps: StepList,
) -> Workflow:
    @functools.wraps(f)
    def wrapping_function() -> NoReturn:
        raise Exception("This function should not be executed")

    wrapping_function = cast(Workflow, wrapping_function)
    wrapping_function.name = f.__name__
    wrapping_function.description = description
    wrapping_function.initial_input_form = initial_input_form
    wrapping_function.steps = steps
    return wrapping_function


def step(name: str) -> Callable[[StepFunc], Step]:
    """Decorator to mark a function as a workflow step."""

    def decorator(func: StepFunc) -> Step:
        @functools.wraps(func)
        def wrapper(state: State) -> Process:
            try:
                result = func(state)
                return Success(result)
            except Exception as ex:
                logger.warning("Step failed", exc_info=ex)
                return Failed({"error": str(ex)})

        return make_step_function(wrapper, name)

    return decorator


def inputstep(name: str) -> Callable[[Callable], Step]:
    """Decorator for user input steps."""

    def decorator(func: Callable) -> Step:
        @functools.wraps(func)
        def suspend(state: State) -> Process:
            return Suspend(state)

        return make_step_function(suspend, name, func)

    return decorator


def workflow(
    description: str,
    initial_input_form: Callable[[State], Any] | None = None,
) -> Callable[[Callable[[], StepList]], Workflow]:
    """Decorator to create a workflow."""

    def _workflow(f: Callable[[], StepList]) -> Workflow:
        return make_workflow(f, description, initial_input_form, f())

    return _workflow


def _purestep(name: str) -> Callable[[Callable[[State], Process]], StepList]:
    def _impl(f: Callable[[State], Process]) -> StepList:
        return StepList([make_step_function(f, name)])

    return _impl


@_purestep("Start")
def init(state: State) -> Process:
    return Success(state)


@_purestep("Done")
def done(state: State) -> Process:
    return Complete(state)


begin = StepList()


# Process execution
@dataclass
class ProcessStat:
    process_id: UUID
    workflow: Workflow
    state: Process
    log: StepList  # Remaining steps
    current_user: str


StepLogFunc = Callable[[ProcessStat, Step, Process], Process]


def _exec_steps(
    steps: StepList,
    starting_process: Process,
    logstep: Callable[[Step, Process], Process],
) -> Process:
    """Execute workflow steps until non-Success/Skipped state."""
    process = starting_process
    for step in steps:
        if not (process.issuccess() or process.isskipped()):
            break

        try:
            step_result = process.execute_step(step)
        except Exception as e:
            logger.error("Step execution failed", exc_info=e)
            step_result = Failed({"error": str(e)})

        process = logstep(step, step_result)

    return process


def runwf(pstat: ProcessStat, logstep: StepLogFunc) -> Process:
    """Run workflow starting from current process state."""
    steps = pstat.log

    def _logstep(step_: Step, p: Process) -> Process:
        return logstep(pstat, step_, p)

    # Resume if suspended
    if pstat.state.issuspend():
        # Pop first step and continue
        if steps:
            resumed_state = Success(pstat.state.unwrap())
            process = _logstep(steps[0], resumed_state)
            return _exec_steps(steps[1:], process, _logstep)

    return _exec_steps(steps, pstat.state, _logstep)