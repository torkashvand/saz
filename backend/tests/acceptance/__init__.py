"""Operator-visible acceptance tests.

These wire up the REAL WorkflowExecutor and run end-to-end with restrained
fakes, in contrast to tests/integration which mocks individual collaborators
with MagicMock. The point is to catch bugs that live at the wiring layer
between planner, grounding, tool registry, and critic — not just at any one
component's interface.
"""
