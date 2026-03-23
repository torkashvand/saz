"""Tool Registry - Central registry for MCP-style tool discovery and execution."""

from collections.abc import Callable
from typing import Any, cast

import structlog

from .ansible_tool import AnsibleTool
from .artifact_tool import ArtifactTool
from .http_tool import HttpTool
from .webhook_tool import WebhookTool

logger = structlog.get_logger(__name__)


_EXTRA_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "word_cap": {
        "type": "integer",
        "description": "Maximum word count for the output text.",
    },
    "branches_enum": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "List of allowed routing destinations. The model MUST choose "
            "exactly one value from this list."
        ),
    },
    "tools_allowlist": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Tool names the model may propose calls to.",
    },
    "target_locale": {
        "type": "string",
        "description": "Target language/locale code for translation (e.g. 'en', 'fr').",
    },
    "top_k": {
        "type": "integer",
        "description": "Maximum number of candidate matches to return.",
    },
}


def _create_ai_tool_spec(op_name: str, op_spec: Any) -> dict[str, Any]:
    """Create MCP-style tool spec for an AI operation with output schema."""
    # Build typed extra-parameter specs instead of generic strings
    extra_properties = {}
    for k in op_spec.input_extras.keys():
        if k in _EXTRA_FIELD_SPECS:
            extra_properties[k] = _EXTRA_FIELD_SPECS[k]
        else:
            extra_properties[k] = {"type": "string", "description": f"{k} parameter"}

    return {
        "name": op_name,
        "description": op_spec.description,
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": (
                        "Task instruction describing what the AI should do. "
                        "Be specific about expected output field names and format."
                    ),
                },
                "data": {
                    "type": "object",
                    "description": "Input data to process. Passed as-is to the AI model.",
                    "additionalProperties": True,
                },
                "expected_schema": {
                    "type": "object",
                    "description": (
                        "JSON Schema for the expected output. For JSON ops, the model "
                        "is instructed to use EXACTLY the property names from this schema."
                    ),
                    "additionalProperties": True,
                },
                "temperature_override": {
                    "type": "number",
                    "description": "Override default temperature (0.0-2.0).",
                    "minimum": 0,
                    "maximum": 2,
                },
                "max_tokens_override": {
                    "type": "integer",
                    "description": "Override default max output tokens.",
                },
                **extra_properties,
            },
            "required": ["instruction"],
        },
        "output_schema": op_spec.default_expect_schema,
    }


class ToolRegistry:
    """
    Central registry for tool discovery and execution.

    Manages:
    - Tool registration and discovery
    - Tool invocation with validation
    - Policy enforcement integration points
    """

    def __init__(
        self,
        http_tool: HttpTool | None = None,
        webhook_tool: WebhookTool | None = None,
        artifact_tool: ArtifactTool | None = None,
        ansible_tool: AnsibleTool | None = None,
    ):
        self.logger = logger.bind(component="tool_registry")
        self._tools: dict[str, dict[str, Any]] = {}
        self._executors: dict[str, Callable] = {}

        # Register core tools
        if http_tool:
            self.register_http_tool(http_tool)
        if webhook_tool:
            self.register_webhook_tool(webhook_tool)
        if artifact_tool:
            self.register_artifact_tool(artifact_tool)
        if ansible_tool:
            self.register_ansible_tool(ansible_tool)

    def register_http_tool(self, http_tool: HttpTool) -> None:
        """Register HTTP tool"""
        self._tools["http_request"] = http_tool.spec
        self._executors["http_request"] = http_tool.execute
        self.logger.info("tool_registered", tool="http_request")

    def register_webhook_tool(self, webhook_tool: WebhookTool) -> None:
        """Register webhook tools"""
        # Webhook emit
        self._tools["webhook_emit"] = webhook_tool.emit_spec
        self._executors["webhook_emit"] = webhook_tool.emit

        # Webhook wait
        self._tools["webhook_wait"] = webhook_tool.wait_spec
        self._executors["webhook_wait"] = webhook_tool.wait_for_webhook

        self.logger.info("tool_registered", tool="webhook_emit")
        self.logger.info("tool_registered", tool="webhook_wait")

    def register_artifact_tool(self, artifact_tool: ArtifactTool) -> None:
        """Register artifact tools"""
        # Artifact store
        self._tools["artifact.store"] = artifact_tool.store_spec
        self._executors["artifact.store"] = artifact_tool.store

        # Artifact retrieve
        self._tools["artifact.retrieve"] = artifact_tool.retrieve_spec
        self._executors["artifact.retrieve"] = artifact_tool.retrieve

        self.logger.info("tool_registered", tool="artifact.store")
        self.logger.info("tool_registered", tool="artifact.retrieve")

    def register_ansible_tool(self, ansible_tool: AnsibleTool) -> None:
        """Register Ansible tool"""
        self._tools["ansible_run"] = ansible_tool.spec
        self._executors["ansible_run"] = ansible_tool.execute
        self.logger.info("tool_registered", tool="ansible_run")

    def register_ai_ops(self, ai_runner: Any) -> None:
        """Register all AI operations as tools."""
        from saz.agents.ai_ops import AI_OPS

        for op_name, op_spec in AI_OPS.items():
            # Create tool spec
            tool_spec = _create_ai_tool_spec(op_name, op_spec)
            self._tools[op_name] = tool_spec

            # Create executor wrapper with proper closure
            def make_executor(op_name_capture: str = op_name) -> Callable:
                async def executor(**kwargs: Any) -> dict[str, Any]:
                    result = await ai_runner.run_ai_op(op_name_capture, **kwargs)
                    return cast(dict[str, Any], result)

                return executor

            self._executors[op_name] = make_executor()
            self.logger.info("ai_op_registered", op=op_name)

        self.logger.info("all_ai_ops_registered", count=len(AI_OPS))

    def register_custom_tool(self, name: str, spec: dict[str, Any], executor: Callable) -> None:
        """
        Register a custom tool.

        Args:
            name: Tool name
            spec: MCP-style tool specification
            executor: Async function to execute the tool
        """
        self._tools[name] = spec
        self._executors[name] = executor
        self.logger.info("custom_tool_registered", tool=name)

    def get_tool_specs(self) -> list[dict[str, Any]]:
        """
        Get all tool specifications for planner agent.

        Returns:
            List of MCP-style tool specs
        """
        return list(self._tools.values())

    def get_tool_specs_dict(self) -> dict[str, dict[str, Any]]:
        """
        Get tool specifications as dict (indexed by name).

        Returns:
            Dict of tool specs
        """
        return self._tools.copy()

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str = "",
        run_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of tool to execute
            arguments: Tool arguments
            idempotency_key: For deduplication
            run_id: Current run ID
            step_id: Current step ID

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found
        """
        if tool_name not in self._executors:
            raise ValueError(f"Tool '{tool_name}' not found in registry")

        executor = self._executors[tool_name]

        self.logger.info(
            "tool_execution_start",
            tool=tool_name,
            run_id=run_id,
            step_id=step_id,
            idempotency_key=idempotency_key,
        )

        try:
            # Add run_id and step_id to arguments if the tool supports them
            exec_args = {**arguments}
            if "run_id" in executor.__code__.co_varnames:
                exec_args["run_id"] = run_id
            if "step_id" in executor.__code__.co_varnames:
                exec_args["step_id"] = step_id
            if "idempotency_key" in executor.__code__.co_varnames:
                exec_args["idempotency_key"] = idempotency_key

            result = await executor(**exec_args)

            self.logger.info(
                "tool_execution_success", tool=tool_name, run_id=run_id, step_id=step_id
            )

            return cast(dict[str, Any], result)

        except Exception as e:
            self.logger.error(
                "tool_execution_failed",
                tool=tool_name,
                error=str(e),
                run_id=run_id,
                step_id=step_id,
            )
            raise

    def list_tools(self) -> list[str]:
        """Get list of registered tool names"""
        return list(self._tools.keys())

    def get_tool_spec(self, tool_name: str) -> dict[str, Any] | None:
        """Get specification for a specific tool"""
        return self._tools.get(tool_name)


def create_default_registry(
    allowed_domains: list[str] | None = None,
    callback_base_url: str = "http://localhost:8000",
    artifact_storage_path: str = "/tmp/saz/artifacts",
    allowed_playbook_roots: list[str] | None = None,
    allowed_inventories: list[str] | None = None,
    enable_ai_ops: bool = True,
) -> ToolRegistry:
    """
    Create a default tool registry with standard tools.

    Args:
        allowed_domains: HTTP domain allowlist
        callback_base_url: Base URL for webhook callbacks
        artifact_storage_path: Path for artifact storage
        allowed_playbook_roots: Ansible playbook allowlist
        allowed_inventories: Ansible inventory allowlist
        enable_ai_ops: Enable AI operations (default: True)

    Returns:
        Configured ToolRegistry
    """
    http_tool = HttpTool(allowed_domains=allowed_domains)
    webhook_tool = WebhookTool(callback_base_url=callback_base_url)
    artifact_tool = ArtifactTool(storage_path=artifact_storage_path)
    ansible_tool = AnsibleTool(
        allowed_playbook_roots=allowed_playbook_roots,
        allowed_inventories=allowed_inventories,
        artifact_storage_path=artifact_storage_path,
    )

    registry = ToolRegistry(
        http_tool=http_tool,
        webhook_tool=webhook_tool,
        artifact_tool=artifact_tool,
        ansible_tool=ansible_tool,
    )

    # Register AI operations
    if enable_ai_ops:
        from saz.agents.ai_ops import get_ai_runner

        ai_runner = get_ai_runner()
        registry.register_ai_ops(ai_runner)

    logger.info(
        "default_registry_created", tools=registry.list_tools(), ai_ops_enabled=enable_ai_ops
    )

    return registry
