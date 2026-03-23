"""AI Operations - First-class AI nodes for workflows.

Each AI op has a strict contract:
- Enforced output format (JSON or text)
- Temperature constraints
- JSON schema validation
- Cost tracking (tokens/USD)

Designed for minimal LLM usage with deterministic fallbacks.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Literal, cast

import structlog

from ..settings import settings
from .llm_port import LLMPort, get_llm_port

logger = structlog.get_logger(__name__)


@dataclass
class AIOpSpec:
    """Specification for an AI operation."""

    name: str
    description: str
    temperature: float
    output_format: Literal["json", "text"]
    default_expect_schema: dict[str, Any]
    input_extras: dict[str, Any] = field(
        default_factory=dict
    )  # tools_allowlist, branches_enum, word_cap, etc.
    max_tokens: int = 2048
    model: str | None = None  # Override default model


# AI Ops Registry
AI_OPS: dict[str, AIOpSpec] = {
    "ai.assess": AIOpSpec(
        name="ai.assess",
        description="Classify, extract structured data, or make a decision. Returns strict JSON.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["result"],
        },
        max_tokens=1024,
    ),
    "ai.generate": AIOpSpec(
        name="ai.generate",
        description=(
            "Compose human-readable text (email, summary, message). "
            "Returns plain text string in the output field."
        ),
        temperature=0.4,
        output_format="text",
        default_expect_schema={
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "Generated text content"},
            },
            "required": ["output"],
        },
        input_extras={"word_cap": 500},
        max_tokens=2048,
    ),
    "ai.plan": AIOpSpec(
        name="ai.plan",
        description="Propose next tool calls based on context. Returns JSON array of tool calls.",
        temperature=0.2,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "rationale": {"type": "string"},
                        },
                        "required": ["tool", "args"],
                    },
                }
            },
            "required": ["calls"],
        },
        input_extras={"tools_allowlist": []},
        max_tokens=2048,
    ),
    "ai.extract": AIOpSpec(
        name="ai.extract",
        description="Pull structured fields from messy text. Returns strict JSON.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={"type": "object", "additionalProperties": True},
        max_tokens=1024,
    ),
    "ai.route": AIOpSpec(
        name="ai.route",
        description="Pick a branch/route based on input. Returns JSON with 'route' field.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {"route": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["route"],
        },
        input_extras={"branches_enum": []},
        max_tokens=512,
    ),
    "ai.score": AIOpSpec(
        name="ai.score",
        description="Numeric scoring against a rubric. Returns JSON with score 0-1.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["score"],
        },
        max_tokens=1024,
    ),
    "ai.normalize": AIOpSpec(
        name="ai.normalize",
        description="Canonicalize names, addresses, or entities. Returns strict JSON.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "normalized": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["normalized"],
        },
        max_tokens=512,
    ),
    "ai.match": AIOpSpec(
        name="ai.match",
        description=(
            "Entity resolution - find matching entity from candidates. "
            "Returns JSON with ID and confidence."
        ),
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string"},
            },
            "required": ["id", "confidence"],
        },
        input_extras={"top_k": 5},
        max_tokens=1024,
    ),
    "ai.evaluate": AIOpSpec(
        name="ai.evaluate",
        description=(
            "Guardrail QA - validate against rules. Returns JSON with pass/fail and issues."
        ),
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "pass": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["pass", "issues"],
        },
        max_tokens=1024,
    ),
    "ai.compare": AIOpSpec(
        name="ai.compare",
        description="Semantic diff or duplicate check. Returns JSON with similarity and deltas.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={
            "type": "object",
            "properties": {
                "same": {"type": "boolean"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "deltas": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["same", "deltas"],
        },
        max_tokens=1024,
    ),
    "ai.translate": AIOpSpec(
        name="ai.translate",
        description="Machine translate with optional glossary. Returns translated text.",
        temperature=0.2,
        output_format="text",
        default_expect_schema={
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "Translated text"},
            },
            "required": ["output"],
        },
        input_extras={"target_locale": "en"},
        max_tokens=2048,
    ),
    "ai.summarize": AIOpSpec(
        name="ai.summarize",
        description="Compress text with constraints. Returns summary text.",
        temperature=0.2,
        output_format="text",
        default_expect_schema={
            "type": "object",
            "properties": {
                "output": {"type": "string", "description": "Summarized text"},
            },
            "required": ["output"],
        },
        input_extras={"word_cap": 100},
        max_tokens=1024,
    ),
    "ai.fix_json": AIOpSpec(
        name="ai.fix_json",
        description="Repair malformed JSON to match schema. Returns valid JSON.",
        temperature=0.1,
        output_format="json",
        default_expect_schema={"type": "object", "additionalProperties": True},
        max_tokens=2048,
    ),
}


class AIOperationsRunner:
    """Execute AI operations with cost tracking and validation."""

    def __init__(
        self,
        default_model: str | None = None,
        cost_per_1m_tokens: float = 0.15,  # Default for gpt-4o-mini
        llm_port: LLMPort | None = None,
    ):
        """
        Initialize AI ops runner.

        Args:
            default_model: Default LLM model (from env if not provided)
            cost_per_1m_tokens: Cost estimate per 1M tokens
            llm_port: LLM client port (defaults to LiteLLM)
        """
        self.default_model = default_model or settings.LLM_MODEL
        self.cost_per_1m_tokens = cost_per_1m_tokens
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(component="ai_ops")

    async def run_ai_op(
        self,
        op_name: str,
        instruction: str,
        data: dict[str, Any] | None = None,
        expected_schema: dict[str, Any] | None = None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute an AI operation.

        Args:
            op_name: Operation name (e.g., "ai.extract")
            instruction: User instruction/prompt
            data: Input data context
            expected_schema: Override default expect schema
            temperature_override: Override default temperature
            max_tokens_override: Override default max_tokens
            **kwargs: Operation-specific extras (tools_allowlist, branches_enum, etc.)

        Returns:
            Dict with:
                - output: Operation result (JSON or text)
                - usage: {tokens: int, cost_usd: float}
                - metadata: {op, temperature, model}
        """
        if op_name not in AI_OPS:
            raise ValueError(f"Unknown AI operation: {op_name}")

        spec = AI_OPS[op_name]

        # Merge parameters
        temperature = temperature_override if temperature_override is not None else spec.temperature
        max_tokens = max_tokens_override if max_tokens_override is not None else spec.max_tokens
        expect_schema = expected_schema or spec.default_expect_schema
        model = spec.model or self.default_model
        assert model is not None, "Model must be specified"

        # Build prompt
        system_prompt = self._build_system_prompt(spec, instruction, expect_schema, kwargs)
        user_message = self._build_user_message(data, kwargs)

        self.logger.info(
            "ai_op_start", op=op_name, temperature=temperature, model=model, max_tokens=max_tokens
        )

        try:
            # Call LLM
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            response_format = {"type": "json_object"} if spec.output_format == "json" else None

            response = await self.llm_port.complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                timeout=30,
            )

            content = response.content
            tokens = response.total_tokens
            cost_usd = (tokens / 1_000_000) * self.cost_per_1m_tokens

            # Parse and validate output
            if spec.output_format == "json":
                try:
                    output = json.loads(content)

                    # Validate against schema if provided
                    if expect_schema:
                        self._validate_json(output, expect_schema)

                except (json.JSONDecodeError, ValueError) as e:
                    # Attempt repair with ai.fix_json
                    self.logger.warning("ai_op_invalid_json", op=op_name, error=str(e))

                    if op_name != "ai.fix_json" and expect_schema is not None:
                        # Retry once with repair
                        output = await self._repair_json(content, expect_schema)
                    else:
                        # Can't repair the repair or no schema to repair against
                        raise ValueError(f"Invalid JSON from {op_name}: {e}") from None
            else:
                output = content

            self.logger.info(
                "ai_op_complete", op=op_name, tokens=tokens, cost_usd=round(cost_usd, 6)
            )

            return {
                "output": output,
                "usage": {"tokens": tokens, "cost_usd": round(cost_usd, 6)},
                "metadata": {
                    "op": op_name,
                    "temperature": temperature,
                    "model": model,
                    "max_tokens": max_tokens,
                },
            }

        except Exception as e:
            self.logger.error("ai_op_failed", op=op_name, error=str(e))
            raise

    def _build_system_prompt(
        self,
        spec: AIOpSpec,
        instruction: str,
        expect_schema: dict[str, Any] | None,
        extras: dict[str, Any],
    ) -> str:
        """Build system prompt for AI op."""
        lines = [
            f"You are an AI assistant performing the operation: {spec.name}",
            f"Task: {spec.description}",
        ]

        # Grounding rules — reduces hallucination and schema drift
        lines.append(
            "\n## Rules"
            "\n- Use ONLY information provided in the input data and instruction."
            "\n- Do NOT invent, assume, or fabricate data not present in the input."
            "\n- For optional fields where information is unavailable, omit the field."
            "\n- For required fields, extract the value from the input."
            " If the input genuinely does not contain the information needed"
            " for a required field, do NOT fabricate a plausible-sounding"
            " value. Instead, produce your best-effort extraction from the"
            " available evidence and let validation catch any gaps."
        )

        lines.append(f"\n## Instruction\n{instruction}")

        # Add constraints from extras
        if "word_cap" in extras or "word_cap" in spec.input_extras:
            word_cap = extras.get("word_cap", spec.input_extras.get("word_cap"))
            lines.append(f"\nConstraint: Limit output to {word_cap} words maximum.")

        if "branches_enum" in extras:
            branches = extras["branches_enum"]
            lines.append(f"\nValid routes: {json.dumps(branches)}")
            lines.append(
                "You MUST choose exactly one route from this list."
                " Do not invent routes outside this list."
            )

        if "tools_allowlist" in extras:
            tools = extras["tools_allowlist"]
            lines.append(f"\nAvailable tools: {json.dumps(tools)}")
            lines.append("You may ONLY propose calls to these tools.")

        if "target_locale" in extras:
            lines.append(f"\nTarget language/locale: {extras['target_locale']}")

        # Schema enforcement — the most critical section for JSON ops
        if spec.output_format == "json" and expect_schema:
            schema_str = json.dumps(expect_schema, indent=2)
            properties = expect_schema.get("properties", {})
            required = expect_schema.get("required", [])
            field_names = list(properties.keys())

            lines.append("\n## Output Schema (STRICT)")
            lines.append(f"```json\n{schema_str}\n```")
            lines.append("\nCRITICAL — You MUST follow this schema exactly:")
            if field_names:
                lines.append(f"- Use EXACTLY these JSON keys: {', '.join(field_names)}")
            if required:
                lines.append(f"- Required fields: {', '.join(required)}")

            # Surface enum constraints explicitly
            for fname, fschema in properties.items():
                if "enum" in fschema:
                    lines.append(
                        f"- Field '{fname}' must be one of: " f"{json.dumps(fschema['enum'])}"
                    )
                if "minimum" in fschema or "maximum" in fschema:
                    lo = fschema.get("minimum", "")
                    hi = fschema.get("maximum", "")
                    lines.append(f"- Field '{fname}' must be a number" f" in range [{lo}, {hi}]")

            lines.append(
                "- Do NOT rename keys, add extra keys, or use"
                " human-readable labels instead of the schema keys."
            )
            lines.append(
                "- Respond with ONLY valid JSON. No markdown, no explanation," " no wrapping."
            )

        return "\n".join(lines)

    def _build_user_message(self, data: dict[str, Any] | None, extras: dict[str, Any]) -> str:
        """Build user message with data context."""
        if not data:
            return "Process the instruction above."

        lines = ["Input data:", json.dumps(data, indent=2, default=str)]

        # Add context from extras
        if "candidates" in extras:
            lines.append("\nCandidates for matching:")
            lines.append(json.dumps(extras["candidates"], indent=2))

        if "rubric" in extras:
            lines.append("\nScoring rubric:")
            lines.append(extras["rubric"])

        if "glossary" in extras:
            lines.append("\nTranslation glossary:")
            lines.append(json.dumps(extras["glossary"], indent=2))

        return "\n".join(lines)

    def _validate_json(self, data: Any, schema: dict[str, Any]) -> None:
        """Validate JSON output against the expected schema.

        Enforces:
        - required fields present
        - no unexpected extra keys (unless additionalProperties is true)
        - type checking (string, number, integer, boolean, array, object)
        - enum constraints
        - numeric bounds (minimum, maximum)
        """
        if schema.get("type") == "object":
            if not isinstance(data, dict):
                raise ValueError(f"Expected object, got {type(data).__name__}")

            required = schema.get("required", [])
            properties = schema.get("properties", {})
            additional = schema.get("additionalProperties", False)

            # Check required fields
            for field in required:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")
                # Required fields must not be None unless schema explicitly allows
                if data[field] is None:
                    field_schema = properties.get(field, {})
                    field_type = field_schema.get("type")
                    if field_type and field_type != "null":
                        raise ValueError(f"Required field '{field}' is null")

            # Reject extra keys unless additionalProperties is allowed
            if properties and not additional:
                extra = set(data.keys()) - set(properties.keys())
                if extra:
                    raise ValueError(
                        f"Unexpected extra fields: {sorted(extra)}. "
                        f"Allowed fields: {sorted(properties.keys())}"
                    )

            # Validate each known property
            for field, field_schema in properties.items():
                if field not in data:
                    continue

                value = data[field]
                field_type = field_schema.get("type")

                # Null handling: null is only valid if the schema has no
                # type constraint or explicitly allows null.  "Optional"
                # means "may be omitted," not "may be null."
                if value is None:
                    if field_type and field_type != "null":
                        raise ValueError(
                            f"Field '{field}' is null but schema requires type '{field_type}'"
                        )
                    continue

                # Type check
                if field_type == "string" and not isinstance(value, str):
                    raise ValueError(f"Field '{field}' must be string, got {type(value).__name__}")
                elif field_type == "integer":
                    if not isinstance(value, int) or isinstance(value, bool):
                        raise ValueError(
                            f"Field '{field}' must be integer, got {type(value).__name__}"
                        )
                elif field_type == "number":
                    if isinstance(value, bool) or not isinstance(value, int | float):
                        raise ValueError(
                            f"Field '{field}' must be number, got {type(value).__name__}"
                        )
                elif field_type == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"Field '{field}' must be boolean, got {type(value).__name__}")
                elif field_type == "array" and not isinstance(value, list):
                    raise ValueError(f"Field '{field}' must be array, got {type(value).__name__}")
                elif field_type == "object" and not isinstance(value, dict):
                    raise ValueError(f"Field '{field}' must be object, got {type(value).__name__}")

                # Enum check
                if "enum" in field_schema:
                    allowed_values = field_schema["enum"]
                    if value not in allowed_values:
                        raise ValueError(
                            f"Field '{field}' has invalid value '{value}'. "
                            f"Must be one of: {allowed_values}"
                        )

                # Bounds check for numbers
                if field_type in ("number", "integer"):
                    if "minimum" in field_schema and value < field_schema["minimum"]:
                        raise ValueError(
                            f"Field '{field}' value {value} below minimum {field_schema['minimum']}"
                        )
                    if "maximum" in field_schema and value > field_schema["maximum"]:
                        raise ValueError(
                            f"Field '{field}' value {value} above maximum {field_schema['maximum']}"
                        )

    async def _repair_json(self, broken_json: str, target_schema: dict[str, Any]) -> dict[str, Any]:
        """Attempt to repair broken JSON using ai.fix_json."""
        self.logger.info("attempting_json_repair")

        repair_result = await self.run_ai_op(
            op_name="ai.fix_json",
            instruction="Repair the following malformed JSON to match the target schema.",
            data={"broken_json": broken_json, "target_schema": target_schema},
            expected_schema=target_schema,
        )

        return cast(dict[str, Any], repair_result["output"])


# Global instance
_ai_runner: AIOperationsRunner | None = None


def get_ai_runner() -> AIOperationsRunner:
    """Get global AI runner instance."""
    global _ai_runner
    if _ai_runner is None:
        _ai_runner = AIOperationsRunner()
    return _ai_runner
