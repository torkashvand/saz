"""Recording fake tools for acceptance tests.

Each FakeTool records (tool_name, arguments, run_id, step_id) for every
invocation and returns a configured response, so acceptance tests can
assert both "did happen" and "did not happen" outcomes.
"""

from collections.abc import Callable
from typing import Any


class RecordingTool:
    """Generic recording tool — registers under any name with any spec."""

    def __init__(
        self,
        name: str,
        response: dict[str, Any] | Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        raises: Exception | None = None,
        spec: dict[str, Any] | None = None,
    ):
        self.name = name
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []
        self.spec = spec or {
            "name": name,
            "description": f"Recording fake tool {name}",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        if callable(self._response):
            return self._response(kwargs)
        return self._response or {"ok": True, "tool": self.name}

    @property
    def call_count(self) -> int:
        return len(self.calls)
