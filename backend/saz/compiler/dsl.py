"""YAML DSL (Domain Specific Language) Compiler for Saz.

Strict DSL (schema_version: 1) with compile-time validation.

## Execution Model
Saz supports two planning modes:

1. **Deterministic** (default): workflow.steps defines the exact execution graph
   - Steps execute in order as written
   - LLMs used INSIDE ai.* steps, not for graph planning
   - Fast, predictable, $0 planning cost

2. **Agentic**: LLM planner generates execution plan dynamically
   - AgenticPlanner reads DSL + tools → generates ExecutionPlan
   - Good for open-ended flows (incident triage, exploratory analysis)
   - Planning cost ~$0.01-0.10 per run

Top-level sections:
- flow: { name (req), description (req), version?, labels?, owners? }
- credentials: { uses: [ "credA", "credB" ] }
- triggers?: { manual?, webhook{event?,path?,signature_header?}?, schedule{cron?,timezone?}? }
- policies?: {
    budget_usd?,
    pii?{ allow?, tokenize_model_inputs?, exceptions?{ tools?{ <tool>: [path, ...] } } },
    rate_limits?{ <tool_name>: { rpm } }
  }
- telemetry?: { trace_level?: "off"|"meta"|"brief"|"verbose", sample_rate?: 0.0-1.0 }
- form?: { fields: [ { name, type, required?, enum?, pattern?, min?, max?, description?, ... } ] }
- workflow: { planner_mode?: "deterministic"|"agentic", steps: [...] }
  - planner_mode: "deterministic" (default) or "agentic"
  - steps: REQUIRED array (non-empty for deterministic, can be empty for agentic)

Allowed step types:
- tool.call         : { id, type, tool, params, expect? }
- ai.assess         : { id, type, instruction, params?, expect? }  # Classification/decisions
- ai.extract        : { id, type, instruction, params?, expect? }  # Structured data extraction
- ai.generate       : { id, type, instruction, params? }           # Text generation (emails, etc)
- ai.route          : { id, type, instruction, branches_enum?, params? }  # Branch selection
- ai.score          : { id, type, instruction, params? }           # Numeric scoring (0-1)
- ai.normalize      : { id, type, instruction, params? }           # Canonicalize entities
- ai.match          : { id, type, instruction, params? }           # Entity resolution
- ai.evaluate       : { id, type, instruction, params? }           # Guardrail QA
- ai.compare        : { id, type, instruction, params? }           # Semantic diff
- ai.translate      : { id, type, instruction, params? }           # Language translation
- ai.summarize      : { id, type, instruction, params? }           # Text summarization
- ai.fix_json       : { id, type, instruction, params? }           # JSON repair
- ai.plan           : { id, type, instruction, params? }           # Tool call planning
- condition         : { id, type, if }
- human.approval    : { id, type, params?, expect? }
- webhook.wait      : { id, type, params{ event_name } }
- artifact.store    : { id, type, params }
- artifact.retrieve : { id, type, params }

Template syntax:
- {{ $form.field_name }}                    → Form data
- {{ $step('step_id').field }}              → Step output field (output key is implicit!)
- {{ $step('step_id') }}                    → Full step output
- {{ $env('VAR') }}                         → Environment variable
- {{ $secret('NAME') }}                     → Credential value

IMPORTANT: Do NOT use {{ $step('id').output.field }} - the .output is automatic!

Output:
- DSLCompiled with form_model, form_schema, workflow_spec, triggers, policies, credentials, warnings
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, cast

import structlog
import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, create_model

from .template_validator import validate_templates

logger = structlog.get_logger(__name__)

# -------------------------------------------------------------------------------------- #
# JSON Schema (draft 2020-12) — intentionally relaxed at the STEP level so compile-time
# validation can produce friendly, precise errors that match tests.
# -------------------------------------------------------------------------------------- #

_DSL_SCHEMA: dict[str, Any] | None = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "flow", "workflow"],
    "properties": {
        "schema_version": {"const": 1},
        "flow": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string"},
                "description": {"type": "string"},
                "labels": {"type": "object", "additionalProperties": {"type": "string"}},
                "owners": {"type": "array", "items": {"type": "string"}},
            },
        },
        "credentials": {
            "type": "object",
            "additionalProperties": False,
            "required": ["uses"],
            "properties": {"uses": {"type": "array", "items": {"type": "string"}}},
        },
        "triggers": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "manual": {"type": "boolean"},
                "webhook": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "event": {"type": "string"},
                        "path": {"type": "string"},
                        "signature_header": {"type": "string"},
                    },
                },
                "schedule": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "cron": {"type": "string"},
                        "timezone": {"type": "string"},
                    },
                },
            },
        },
        "policies": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "budget_usd": {"type": "number", "minimum": 0},
                "concurrency": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "per_flow": {"type": "integer", "minimum": 1},
                        "per_user": {"type": "integer", "minimum": 1},
                    },
                },
                "defaults": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "retry": {"$ref": "#/$defs/retry"},
                        "timeout_ms": {"type": "integer", "minimum": 1},
                        "continue_on_fail": {"type": "boolean"},
                    },
                },
                "pii": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "allow": {
                            "type": "boolean",
                            "description": (
                                "If true, PII is allowed (less restrictive). "
                                "If false, PII is blocked by default."
                            ),
                        },
                        "tokenize_model_inputs": {
                            "type": "boolean",
                            "description": (
                                "If true, PII is tokenized before model tool invocations. "
                                "Default: true."
                            ),
                        },
                        "exceptions": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tools": {
                                    "type": "object",
                                    "additionalProperties": {
                                        "oneOf": [
                                            {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "required": ["allow"],
                                                "properties": {
                                                    "allow": {
                                                        "type": "array",
                                                        "items": {"type": "string"},
                                                        "description": (
                                                            "Dotted paths where PII is allowed "
                                                            "for this tool"
                                                        ),
                                                    }
                                                },
                                            },
                                            {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": (
                                                    "Shorthand: array of dotted paths where "
                                                    "PII is allowed"
                                                ),
                                            },
                                        ]
                                    },
                                    "description": (
                                        "Per-tool PII allow-lists. Maps tool name to "
                                        "allowed argument paths."
                                    ),
                                }
                            },
                            "description": "Exceptions to PII blocking rules",
                        },
                    },
                },
                "rate_limits": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["rpm"],
                        "properties": {"rpm": {"type": "integer", "minimum": 1}},
                    },
                },
            },
        },
        "telemetry": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "trace_level": {
                    "type": "string",
                    "enum": ["off", "meta", "brief", "verbose"],
                    "description": (
                        "Trace level: off (no telemetry), meta (minimal), "
                        "brief (+ tool calls/policy), verbose (+ input summaries)"
                    ),
                },
                "sample_rate": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": "Sampling rate for telemetry (0.0-1.0, default 1.0)",
                },
            },
        },
        "form": {
            "type": "object",
            "additionalProperties": False,
            "required": ["fields"],
            "properties": {
                "fields": {"type": "array", "items": {"$ref": "#/$defs/form_field"}},
            },
        },
        "workflow": {
            "type": "object",
            "additionalProperties": False,
            "required": ["planner_mode", "steps"],
            "properties": {
                "planner_mode": {
                    "type": "string",
                    "enum": ["deterministic", "agentic"],
                    "description": (
                        "Planning mode: deterministic (fixed steps) or agentic (LLM planning)"
                    ),
                },
                "steps": {
                    "type": "array",
                    # For agentic mode, steps can be empty (planner generates them)
                    # For deterministic mode, steps must be non-empty (validated separately)
                    "items": {"$ref": "#/$defs/stepBase"},
                },
            },
        },
    },
    "$defs": {
        "backoff": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"enum": ["constant", "linear", "exponential"]},
                "base_ms": {"type": "integer", "minimum": 0},
                "max_ms": {"type": "integer", "minimum": 0},
                "jitter": {"type": "boolean"},
            },
        },
        "retry": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "attempts": {"type": "integer", "minimum": 0},
                "backoff": {"$ref": "#/$defs/backoff"},
            },
        },
        "form_field": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "type"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                # Accept 'text' alias; parse-time normalization will convert to 'string'
                "type": {"enum": ["string", "integer", "number", "boolean", "text"]},
                "required": {"type": "boolean"},
                "enum": {"type": "array"},
                "pattern": {"type": "string"},
                "minLength": {"type": "integer", "minimum": 0},
                "maxLength": {"type": "integer", "minimum": 0},
                "format": {"enum": ["email", "uri"]},
                # Accept both canonical and aliases (minimum/maximum and min/max)
                "minimum": {"type": "number"},
                "maximum": {"type": "number"},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "description": {"type": "string"},
                "title": {"type": "string"},
                "default": {},
                # Allow 'regex' as alias for 'pattern'
                "regex": {"type": "string"},
            },
        },
        # Super-light step shape, so deep checks happen in compile_dsl()
        "stepBase": {
            "type": "object",
            "required": ["id", "type"],
            "properties": {
                "id": {"type": "string", "minLength": 1},
                "type": {"type": "string"},
            },
            "additionalProperties": True,
        },
    },
}

# -------------------------------------------------------------------------------------- #
# Runtime constants                                                                      #
# -------------------------------------------------------------------------------------- #

# Step types accepted by the compiler. Must mirror what
# engine/executor.py:_execute_step_action() can actually dispatch — a
# compiler-allowed step that the runtime cannot run lets invalid flows pass
# /flows/compile and crash at execute time with "Unknown step_type".
#
# group.parallel / group.map / noop were declared here historically but were
# never implemented in the executor and no shipped example workflow uses
# them; removed until/unless the runtime side lands.
_ALLOWED_STEP_TYPES: set[str] = {
    "tool.call",
    "condition",
    "human.approval",
    "webhook.wait",
    "artifact.store",
    "artifact.retrieve",
    "ai.extract",
    "ai.generate",
    "ai.route",
    "ai.score",
    "ai.assess",
    "ai.normalize",
    "ai.match",
    "ai.evaluate",
    "ai.compare",
    "ai.translate",
    "ai.summarize",
    "ai.fix_json",
    "ai.plan",
}


_STR_FORMAT_PATTERNS: dict[str, str] = {
    "email": r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$",
    "uri": r"^[a-zA-Z][a-zA-Z0-9+.\-]*://.+$",
}

# -------------------------------------------------------------------------------------- #
# Result wrapper                                                                         #
# -------------------------------------------------------------------------------------- #


@dataclass
class DSLCompiled:
    """Result of compiling a DSL YAML."""

    flow_name: str
    flow_version: str | None
    flow_description: str | None
    form_model: type[BaseModel]
    form_schema: dict[str, Any]
    workflow_spec: dict[str, Any]
    triggers: dict[str, Any]
    policies: dict[str, Any]
    credentials: list[str]
    raw_dsl: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def json_schema(self) -> dict[str, Any]:
        return self.form_schema


# -------------------------------------------------------------------------------------- #
# Helpers                                                                                #
# -------------------------------------------------------------------------------------- #


def _normalize_pre_schema(dsl: dict[str, Any]) -> dict[str, Any]:
    """Normalize common aliases before JSON-Schema validation."""
    if "_schema_version" in dsl and "schema_version" not in dsl:
        dsl["schema_version"] = dsl.pop("_schema_version")
    if "schemaVersion" in dsl and "schema_version" not in dsl:
        dsl["schema_version"] = dsl.pop("schemaVersion")

    sv = dsl.get("schema_version")
    if isinstance(sv, int | float) and (sv == 1 or sv == 1.0):
        dsl["schema_version"] = 1
    elif isinstance(sv, str) and sv.strip() == "1":
        dsl["schema_version"] = 1

    # form field aliases
    form = dsl.get("form")
    if isinstance(form, dict):
        fields = form.get("fields", [])
        if isinstance(fields, list):
            for fd in fields:
                if not isinstance(fd, dict):
                    continue
                t = fd.get("type")
                # Normalize type aliases *before* schema validation
                if t == "text":
                    fd["type"] = "string"
                elif t == "int":
                    fd["type"] = "integer"
                elif t == "float":
                    fd["type"] = "number"

                # regex -> pattern
                if "regex" in fd and "pattern" not in fd:
                    fd["pattern"] = fd["regex"]
                fd.pop("regex", None)

                # min/max -> minimum/maximum
                if "min" in fd and "minimum" not in fd:
                    fd["minimum"] = fd["min"]
                if "max" in fd and "maximum" not in fd:
                    fd["maximum"] = fd["max"]
                fd.pop("min", None)
                fd.pop("max", None)

    return dsl


# -------------------------------------------------------------------------------------- #
# Parse & top-level validation                                                           #
# -------------------------------------------------------------------------------------- #


def parse_yaml(yaml_content: str) -> dict[str, Any]:
    """Parse YAML and perform structural checks with friendly errors."""
    try:
        dsl = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}") from None

    if not isinstance(dsl, dict):
        raise ValueError("YAML root must be a dictionary")

    dsl = _normalize_pre_schema(dsl)

    # Friendly errors expected by tests
    if "schema_version" not in dsl:
        raise ValueError(
            "Missing required property 'schema_version'; "
            "add 'schema_version: 1' at the top of the file"
        )
    if "flow" not in dsl or not isinstance(dsl["flow"], dict) or "name" not in dsl["flow"]:
        raise ValueError("flow.name is required")
    if "description" not in dsl["flow"] or not dsl["flow"]["description"]:
        raise ValueError("flow.description is required and must be non-empty")
    if "workflow" not in dsl or not isinstance(dsl["workflow"], dict):
        raise ValueError("workflow is required")
    if "planner_mode" not in dsl["workflow"]:
        raise ValueError("workflow.planner_mode is required (must be 'deterministic' or 'agentic')")
    if "steps" not in dsl["workflow"]:
        raise ValueError("workflow.steps is required")

    # Validate planner_mode
    planner_mode = dsl["workflow"]["planner_mode"]
    if planner_mode not in {"deterministic", "agentic"}:
        raise ValueError(
            f"workflow.planner_mode must be 'deterministic' or 'agentic', got: {planner_mode}"
        )

    # For deterministic mode, steps must be non-empty
    # For agentic mode, steps can be empty (planner generates them)
    if planner_mode == "deterministic":
        if isinstance(dsl["workflow"]["steps"], list) and len(dsl["workflow"]["steps"]) == 0:
            raise ValueError(
                "workflow.steps must be non-empty when planner_mode is 'deterministic'"
            )

    if "form" in dsl:
        if not isinstance(dsl["form"], dict) or "fields" not in dsl["form"]:
            raise ValueError("form.fields is required")

    # JSON Schema pass
    validator = Draft202012Validator(_DSL_SCHEMA)
    errors = sorted(validator.iter_errors(dsl), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.path) or "<root>"
        raise ValueError(f"DSL does not conform to schema at {path}: {first.message}")

    logger.info(
        "dsl_parsed",
        flow_name=dsl["flow"]["name"],
        fields_count=len(dsl.get("form", {}).get("fields", [])),
        steps_count=len(dsl["workflow"]["steps"]),
        schema_version=dsl.get("schema_version"),
    )
    return dsl


# -------------------------------------------------------------------------------------- #
# Form compilation                                                                       #
# -------------------------------------------------------------------------------------- #


def _pydantic_type(field_type: str) -> type:
    """Map DSL field type to Python type."""
    match field_type:
        case "string" | "text":
            return str
        case "integer" | "int":
            return int
        case "number" | "float":
            return float
        case "boolean":
            return bool
        case "array":
            return list
        case "object":
            return dict
        case _:
            raise ValueError(f"Unsupported form field type: {field_type!r}")


def compile_form_model(form_def: dict[str, Any]) -> tuple[type[BaseModel], dict[str, Any]]:
    """Compile form definition to Pydantic model and JSON Schema."""
    fields_def: list[dict[str, Any]] = form_def.get("fields", [])

    pyd_fields: dict[str, tuple[Any, Any]] = {}

    for fd in fields_def:
        if not isinstance(fd, dict):
            raise ValueError("form.fields items must be objects")
        if "name" not in fd or "type" not in fd:
            raise ValueError("Each form field requires 'name' and 'type'")

        name: str = fd["name"]
        type_str: str = fd["type"]
        required: bool = bool(fd.get("required", True))

        base_type = _pydantic_type(type_str)

        field_kwargs: dict[str, Any] = {}

        # string constraints
        if base_type is str:
            if "minLength" in fd:
                field_kwargs["min_length"] = int(fd["minLength"])
            if "maxLength" in fd:
                field_kwargs["max_length"] = int(fd["maxLength"])
            pattern = fd.get("pattern") or fd.get("regex")
            fmt = fd.get("format")
            if fmt and fmt in _STR_FORMAT_PATTERNS and not pattern:
                pattern = _STR_FORMAT_PATTERNS[fmt]
            if pattern:
                try:
                    re.compile(pattern)
                except re.error as e:
                    raise ValueError(f"Invalid regex for field '{name}': {e}") from None
                field_kwargs["pattern"] = pattern

        # numeric constraints (support canonical + min/max aliases)
        if base_type in (int, float):
            if "minimum" in fd or "min" in fd:
                field_kwargs["ge"] = fd.get("minimum", fd.get("min"))
            if "maximum" in fd or "max" in fd:
                field_kwargs["le"] = fd.get("maximum", fd.get("max"))

        # metadata
        if "description" in fd:
            field_kwargs["description"] = fd["description"]
        if "title" in fd:
            field_kwargs["title"] = fd["title"]

        # explicit default (including None)
        explicit_default_present = "default" in fd
        explicit_default = fd.get("default", None)

        # enum (UI uses JSON Schema enum)
        if "enum" in fd and isinstance(fd["enum"], list):
            field_kwargs.setdefault("json_schema_extra", {})
            field_kwargs["json_schema_extra"]["enum"] = fd["enum"]

        if required:
            if explicit_default_present:
                pyd_fields[name] = (base_type, Field(default=explicit_default, **field_kwargs))
            else:
                pyd_fields[name] = (base_type, Field(**field_kwargs) if field_kwargs else ...)
        else:
            pyd_fields[name] = (base_type | None, Field(default=explicit_default, **field_kwargs))

    model_cls = create_model("FormModel", **pyd_fields)  # type: ignore[call-overload]
    json_schema = cast(dict[str, Any], model_cls.model_json_schema())

    # move our "enum" back into properties for consumers
    for _, spec in json_schema.get("properties", {}).items():
        extra = spec.get("json_schema_extra")
        if isinstance(extra, dict) and "enum" in extra:
            spec["enum"] = extra["enum"]
            spec.pop("json_schema_extra", None)

    return cast(type[BaseModel], model_cls), json_schema


# -------------------------------------------------------------------------------------- #
# Workflow validation & normalization                                                    #
# -------------------------------------------------------------------------------------- #


def _require_keys(step: dict[str, Any], keys: list[str]) -> None:
    for k in keys:
        if k not in step:
            sid = step.get("id", "<missing-id>")
            raise ValueError(f"workflow step '{sid}' missing key: {k}")


def _validate_retry(retry: dict[str, Any]) -> None:
    if not isinstance(retry, dict):
        raise ValueError("retry must be an object")
    if "attempts" in retry and int(retry["attempts"]) < 0:
        raise ValueError("retry.attempts must be >= 0")
    backoff = retry.get("backoff")
    if backoff is not None:
        if not isinstance(backoff, dict):
            raise ValueError("retry.backoff must be an object")
        mode = backoff.get("mode")
        if mode not in {"constant", "linear", "exponential"}:
            raise ValueError("retry.backoff.mode must be constant|linear|exponential")
        for k in ("base_ms", "max_ms"):
            if k in backoff and int(backoff[k]) < 0:
                raise ValueError(f"retry.backoff.{k} must be >= 0")
        if "jitter" in backoff and not isinstance(backoff["jitter"], bool):
            raise ValueError("retry.backoff.jitter must be boolean")


def _validate_and_normalize_steps(
    steps: list[dict[str, Any]], credential_names: set[str]
) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    norm: list[dict[str, Any]] = []

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"workflow.steps[{idx}] must be an object")

        # id
        sid = step.get("id")
        if not sid or not isinstance(sid, str):
            raise ValueError(f"workflow.steps[{idx}] must include string 'id'")
        if sid in seen_ids:
            raise ValueError(f"Duplicate step id: {sid}")
        seen_ids.add(sid)

        # Get step type
        stype: str = cast(str, step.get("type", "tool.call"))
        step["type"] = stype

        if stype not in _ALLOWED_STEP_TYPES:
            raise ValueError(f"Unknown step type '{stype}' in step '{sid}'")

        # per-type requirements
        if stype == "tool.call":
            _require_keys(step, ["tool", "params"])
            if not isinstance(step["params"], dict):
                raise ValueError(f"step '{sid}' params must be an object")
            # Require description for human intent
            if "description" not in step or not step["description"]:
                raise ValueError(
                    f"step '{sid}' (type: tool.call) requires non-empty 'description' field "
                    "to document human intent"
                )
        elif stype.startswith("ai."):
            # All AI operations require instruction
            if "instruction" not in step or not step["instruction"]:
                raise ValueError(
                    f"step '{sid}' (type: {stype}) requires non-empty 'instruction' field"
                )
            # All AI operations require expected output schema
            if "expect" not in step or not step["expect"]:
                raise ValueError(
                    f"step '{sid}' (type: {stype}) requires 'expect' field with "
                    f"expected output schema (properties, required fields, enums). "
                    f"Without it, output validation is weak and the model may "
                    f"return wrong field names."
                )
        elif stype == "condition":
            _require_keys(step, ["if"])
            if "description" not in step or not step["description"]:
                raise ValueError(
                    f"step '{sid}' (type: condition) requires non-empty 'description' field"
                )
        elif stype == "human.approval":
            if "description" not in step or not step["description"]:
                raise ValueError(
                    f"step '{sid}' (type: human.approval) requires non-empty 'description' field"
                )
        elif stype == "webhook.wait":
            params = step.get("params")
            if not isinstance(params, dict) or "event_name" not in params:
                raise ValueError(f"step '{sid}' webhook.wait requires params.event_name")
            if "description" not in step or not step["description"]:
                raise ValueError(
                    f"step '{sid}' (type: webhook.wait) requires non-empty 'description' field"
                )
        elif stype in {"artifact.store", "artifact.retrieve"}:
            _require_keys(step, ["params"])
            if not isinstance(step["params"], dict):
                raise ValueError(f"step '{sid}' params must be an object")
            if "description" not in step or not step["description"]:
                raise ValueError(
                    f"step '{sid}' (type: {stype}) requires non-empty 'description' field"
                )

        # uses_credentials
        creds = step.get("uses_credentials", [])
        if creds is None:
            creds = []
        if not isinstance(creds, list) or not all(isinstance(c, str) for c in creds):
            raise ValueError(f"step '{sid}' uses_credentials must be a string list if present")
        unknown = [c for c in creds if c not in credential_names]
        if unknown:
            raise ValueError(f"step '{sid}' references unknown credentials: {unknown}")

        # retry (optional)
        if "retry" in step:
            _validate_retry(cast(dict[str, Any], step["retry"]))

        # ensure containers exist
        step.setdefault("params", step.get("params", {}))
        step.setdefault("retry", step.get("retry", {}))
        norm.append(step)

    return norm


def compile_workflow_spec(workflow_def: dict[str, Any], flow_name: str) -> dict[str, Any]:
    """Build workflow spec skeleton; planner_mode is required."""
    steps = cast(list[dict[str, Any]], workflow_def.get("steps", []))
    planner_mode = workflow_def["planner_mode"]  # Required, validated in parse_yaml
    return {"name": flow_name, "planner_mode": planner_mode, "steps": steps}


# -------------------------------------------------------------------------------------- #
# Triggers / Policies / Credentials                                                      #
# -------------------------------------------------------------------------------------- #


def _compile_triggers(triggers: dict[str, Any] | None) -> dict[str, Any]:
    if not triggers:
        return {"manual": True}
    out: dict[str, Any] = {"manual": bool(triggers.get("manual", True))}
    if "webhook" in triggers:
        wh = triggers["webhook"] or {}
        out["webhook"] = {
            "event": wh.get("event"),
            "path": wh.get("path"),
            "signature_header": wh.get("signature_header"),
        }
    if "schedule" in triggers:
        sch = triggers["schedule"] or {}
        out["schedule"] = {"cron": sch.get("cron"), "timezone": sch.get("timezone")}
    return out


def _compile_policies(p: dict[str, Any] | None) -> dict[str, Any]:
    p = p or {}
    defaults = p.get("defaults", {})
    retry = defaults.get("retry", {})

    if "budget_usd" in p and float(p["budget_usd"]) < 0:
        raise ValueError("policies.budget_usd must be >= 0")
    if "concurrency" in p:
        conc = p["concurrency"]
        if not isinstance(conc, dict):
            raise ValueError("policies.concurrency must be an object")
        for key in ("per_flow", "per_user"):
            if key in conc and int(conc[key]) < 1:
                raise ValueError(f"policies.concurrency.{key} must be >= 1")
    if retry:
        _validate_retry(retry)

    return {
        "budget_usd": float(p.get("budget_usd", 10.0)),
        "concurrency": p.get("concurrency", {}),
        "defaults": {
            "retry": retry,
            "timeout_ms": int(defaults.get("timeout_ms", 15_000)),
            "continue_on_fail": bool(defaults.get("continue_on_fail", False)),
        },
        "pii": {"allow": bool(p.get("pii", {}).get("allow", False))},
        "rate_limits": p.get("rate_limits", {}),
        "max_replan_attempts": int(p.get("max_replan_attempts", 3)),
    }


def _compile_credentials(creds: Any) -> tuple[list[str], list[dict[str, Any]]]:
    """Extract credential names from credentials section."""
    if creds is None:
        return [], []

    if not isinstance(creds, dict) or "uses" not in creds:
        raise ValueError("credentials must be an object with 'uses' array")

    uses = creds.get("uses", []) or []
    if not isinstance(uses, list) or not all(isinstance(x, str) for x in uses):
        raise ValueError("credentials.uses must be a list of strings")

    names = list(uses)
    if len(set(names)) != len(names):
        raise ValueError("credentials contain duplicate names")

    out = [{"name": n, "required_scopes": []} for n in names]
    return names, out


# -------------------------------------------------------------------------------------- #
# Public compile entry                                                                   #
# -------------------------------------------------------------------------------------- #


def compile_policies(policies_def: dict[str, Any] | None) -> dict[str, Any]:
    """Exported for tests – normalized policy shape."""
    return _compile_policies(policies_def)


def compile_dsl(yaml_content: str) -> DSLCompiled:
    """Compile DSL to executable components."""
    dsl = parse_yaml(yaml_content)

    flow = cast(dict[str, Any], dsl["flow"])
    form = cast(dict[str, Any], dsl.get("form", {"fields": []}))
    workflow = cast(dict[str, Any], dsl["workflow"])
    triggers_in = cast(dict[str, Any] | None, dsl.get("triggers"))
    policies_in = cast(dict[str, Any] | None, dsl.get("policies"))
    creds_in = dsl.get("credentials")

    # Credentials first (step validation needs the names)
    cred_names, cred_objects = _compile_credentials(creds_in)

    # Form model/schema
    form_model, form_schema = compile_form_model(form)

    # Workflow skeleton + deep validation
    workflow_spec = compile_workflow_spec(workflow, flow["name"])
    normalized_steps = _validate_and_normalize_steps(
        cast(list[dict[str, Any]], workflow_spec.get("steps", [])),
        credential_names=set(cred_names),
    )
    workflow_spec["steps"] = normalized_steps

    # Triggers + Policies
    triggers = _compile_triggers(triggers_in)
    policies = _compile_policies(policies_in)

    # Validate template expressions
    form_field_names = [f["name"] for f in form.get("fields", [])]
    step_ids = [s["id"] for s in normalized_steps]
    template_warnings, template_errors = validate_templates(
        workflow_spec, form_field_names, step_ids
    )

    # Raise errors if any template validation failed
    if template_errors:
        error_msg = "Template validation failed:\n" + "\n".join(f"  - {e}" for e in template_errors)
        raise ValueError(error_msg)

    logger.info(
        "dsl_compiled",
        flow_name=flow["name"],
        form_fields=len(form.get("fields", [])),
        workflow_steps=len(normalized_steps),
        credentials=len(cred_names),
        template_warnings=len(template_warnings),
    )

    return DSLCompiled(
        flow_name=flow["name"],
        flow_version=cast(str | None, flow.get("version")),
        flow_description=cast(str | None, flow.get("description")),
        form_model=form_model,
        form_schema=form_schema,
        workflow_spec=workflow_spec,
        triggers=triggers,
        policies=policies,
        credentials=cred_names,
        raw_dsl=dsl | {"credentials_normalized": cred_objects},
        warnings=template_warnings,
    )
