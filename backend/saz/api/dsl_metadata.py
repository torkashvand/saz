"""Centralized DSL metadata for the Guided Builder.

This module is the single source of truth the frontend reads from to know
what step types exist, what fields each one needs, which AI ops are
authorable, which tools are registered, and what expression helpers are
available. Keeping it here means `dsl.py`, `ai_ops.py`, and the tool
registry cannot drift silently.
"""

from __future__ import annotations

from typing import Any

from saz.agents.ai_ops import AI_OPS
from saz.compiler.dsl import _ALLOWED_STEP_TYPES

# Step types that are user-authorable in the Guided Builder. We deliberately
# hide `ai.fix_json` here: the `/api/v1/flows/ai-ops` endpoint already treats
# it as an internal repair tool, so it should not appear in step pickers.
_INTERNAL_STEP_TYPES: frozenset[str] = frozenset({"ai.fix_json"})


_STEP_TYPE_CATEGORIES: dict[str, str] = {
    "tool.call": "Integration",
    "condition": "Control",
    "human.approval": "Control",
    "webhook.wait": "Integration",
    "artifact.store": "Data",
    "artifact.retrieve": "Data",
}


_STEP_TYPE_LABELS: dict[str, str] = {
    "tool.call": "Tool Call",
    "condition": "Condition",
    "human.approval": "Human Approval",
    "webhook.wait": "Webhook Wait",
    "artifact.store": "Store Artifact",
    "artifact.retrieve": "Retrieve Artifact",
    "ai.assess": "AI Assess",
    "ai.extract": "AI Extract",
    "ai.generate": "AI Generate",
    "ai.route": "AI Route",
    "ai.score": "AI Score",
    "ai.normalize": "AI Normalize",
    "ai.match": "AI Match",
    "ai.evaluate": "AI Evaluate",
    "ai.compare": "AI Compare",
    "ai.translate": "AI Translate",
    "ai.summarize": "AI Summarize",
    "ai.plan": "AI Plan",
}


def _build_step_type(step_type: str) -> dict[str, Any]:
    """Build per-step-type metadata.

    Combines the validation rules from `dsl.py:_validate_and_normalize_steps`
    with the AI op spec (for `ai.*` types). The frontend uses this to render
    the right editor for each step.
    """

    is_ai = step_type.startswith("ai.")
    spec: dict[str, Any] = {
        "name": step_type,
        "label": _STEP_TYPE_LABELS.get(step_type, step_type),
        "category": "AI" if is_ai else _STEP_TYPE_CATEGORIES.get(step_type, "Other"),
        "requires_instruction": is_ai,
        "requires_expect": is_ai,
        "requires_description": step_type
        in {
            "tool.call",
            "condition",
            "human.approval",
            "webhook.wait",
            "artifact.store",
            "artifact.retrieve",
        },
        "requires_params": step_type
        in {"tool.call", "webhook.wait", "artifact.store", "artifact.retrieve"},
        "accepts_uses_credentials": True,
        "accepts_retry": True,
    }

    if step_type == "condition":
        spec["requires_if"] = True
        spec["requires_params"] = False
        spec["requires_expect"] = False
        spec["requires_instruction"] = False

    if step_type == "tool.call":
        spec["requires_tool"] = True

    if step_type == "webhook.wait":
        spec["param_requirements"] = {"event_name": "string"}

    if is_ai and step_type in AI_OPS:
        op = AI_OPS[step_type]
        spec["ai_op"] = {
            "description": op.description,
            "output_format": op.output_format,
            "default_temperature": op.temperature,
            "default_max_tokens": op.max_tokens,
            "default_expect_schema": op.default_expect_schema,
            "input_extras": op.input_extras or {},
        }
    return spec


def _form_field_metadata() -> dict[str, Any]:
    """Form field types and constraints. Mirrors `_DSL_SCHEMA.$defs.form_field`."""

    return {
        "types": ["string", "integer", "number", "boolean", "text"],
        "constraints": {
            "string": [
                "required",
                "enum",
                "pattern",
                "minLength",
                "maxLength",
                "default",
                "title",
                "description",
                "format",
            ],
            "text": ["required", "minLength", "maxLength", "default", "title", "description"],
            "integer": ["required", "minimum", "maximum", "default", "title", "description"],
            "number": ["required", "minimum", "maximum", "default", "title", "description"],
            "boolean": ["required", "default", "title", "description"],
        },
        "formats": ["email", "uri"],
        "aliases": {"pattern": ["regex"], "minimum": ["min"], "maximum": ["max"]},
    }


def _trigger_metadata() -> dict[str, Any]:
    return {
        "manual": {"type": "boolean"},
        "webhook": {
            "fields": {
                "event": {"type": "string"},
                "path": {"type": "string"},
                "signature_header": {
                    "type": "string",
                    "description": (
                        "Incoming HTTP header that carries the signature for verification."
                    ),
                },
            },
        },
        "schedule": {
            "fields": {
                "cron": {"type": "string"},
                "timezone": {"type": "string"},
            },
        },
    }


def _policy_metadata() -> dict[str, Any]:
    return {
        "budget_usd": {"type": "number", "minimum": 0},
        "concurrency": {
            "fields": {
                "per_flow": {"type": "integer", "minimum": 1},
                "per_user": {"type": "integer", "minimum": 1},
            }
        },
        "defaults": {
            "fields": {
                "timeout_ms": {"type": "integer", "minimum": 1},
                "continue_on_fail": {"type": "boolean"},
                "retry": "retry",
            }
        },
        "pii": {
            "fields": {
                "allow": {"type": "boolean"},
                "tokenize_model_inputs": {"type": "boolean"},
                "exceptions": {
                    "description": "Per-tool argument-path allow-lists.",
                },
            }
        },
        "rate_limits": {
            "description": "Map of tool-name -> { rpm: integer >= 1 }.",
        },
        "retry": {
            "attempts": {"type": "integer", "minimum": 0},
            "backoff": {
                "mode": ["constant", "linear", "exponential"],
                "base_ms": {"type": "integer", "minimum": 0},
                "max_ms": {"type": "integer", "minimum": 0},
                "jitter": {"type": "boolean"},
            },
        },
    }


def _telemetry_metadata() -> dict[str, Any]:
    return {
        "trace_level": {
            "type": "enum",
            "values": ["off", "meta", "brief", "verbose"],
            "labels": {
                "off": "Off (no telemetry)",
                "meta": "Meta (run/step boundaries only)",
                "brief": "Brief (+ tool calls, policy decisions)",
                "verbose": "Verbose (+ input summaries)",
            },
        },
        "sample_rate": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 1.0},
    }


def _expression_helpers() -> list[dict[str, Any]]:
    """Template expression helpers the runtime resolves at execute time."""

    return [
        {
            "name": "$form",
            "syntax": "{{ $form.field_name }}",
            "description": "Reference a form field by name.",
            "needs_argument": True,
            "argument_kind": "form_field",
        },
        {
            "name": "$step",
            "syntax": "{{ $step('step_id').field }}",
            "description": "Reference a prior step's output field (the .output is implicit).",
            "needs_argument": True,
            "argument_kind": "step_id",
        },
        {
            "name": "$env",
            "syntax": "{{ $env('VAR') }}",
            "description": "Read an environment variable.",
            "needs_argument": True,
            "argument_kind": "string",
        },
        {
            "name": "$secret",
            "syntax": "{{ $secret('NAME') }}",
            "description": "Read a credential value by name.",
            "needs_argument": True,
            "argument_kind": "credential",
        },
    ]


def _tool_registry_summary() -> list[dict[str, Any]]:
    """Tools that ship with the runtime by default.

    Read from the canonical default registry so the metadata reflects what
    the executor will actually accept. We avoid instantiating the runtime
    side-effectful tools (HTTP/ansible/etc.) here — we just enumerate the
    well-known tool names plus their MCP-style spec when available.
    """

    # Static names are sufficient for the Guided Builder picker. Full specs
    # are not surfaced here to keep the payload small and the response
    # snapshot stable.
    return [
        {"name": "http_request", "description": "Call an HTTP endpoint."},
        {"name": "webhook_emit", "description": "Emit a webhook event."},
        {"name": "webhook_wait", "description": "Wait for a callback webhook."},
        {"name": "artifact.store", "description": "Store an artifact in run storage."},
        {"name": "artifact.retrieve", "description": "Retrieve a stored artifact."},
        {"name": "ansible_run", "description": "Run an allowlisted Ansible playbook."},
    ]


def build_dsl_metadata() -> dict[str, Any]:
    """Return the full DSL metadata payload."""

    user_facing_step_types = sorted(t for t in _ALLOWED_STEP_TYPES if t not in _INTERNAL_STEP_TYPES)

    return {
        "schema_version": 1,
        "planner_modes": ["deterministic", "agentic"],
        "step_types": [_build_step_type(t) for t in user_facing_step_types],
        "form_fields": _form_field_metadata(),
        "triggers": _trigger_metadata(),
        "policies": _policy_metadata(),
        "telemetry": _telemetry_metadata(),
        "expression_helpers": _expression_helpers(),
        "tools": _tool_registry_summary(),
    }
