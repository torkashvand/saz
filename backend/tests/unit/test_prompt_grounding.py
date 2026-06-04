"""Tests for prompt grounding and anti-hallucination improvements.

Proves that:
- AI-op prompts enforce schema key names explicitly
- AI-op prompts surface enum constraints from schema
- AI-op prompts include grounding rules against fabrication
- Verifier prompt includes evidence-based decision policy
- Critic prompt highlights schema conformance as priority check
- Tool specs use typed extras (not generic strings)
- Planner prompt includes grounding rules against invented tools/fields
"""

from saz.agents.agentic_planner import PLANNER_SYSTEM_PROMPT
from saz.agents.ai_ops import AI_OPS, AIOperationsRunner
from saz.agents.critic import CRITIC_SYSTEM_PROMPT, VERIFIER_SYSTEM_PROMPT
from saz.tools.registry import _create_ai_tool_spec

# ---------------------------------------------------------------------------
# AI-op prompt grounding
# ---------------------------------------------------------------------------


def test_ai_op_prompt_includes_exact_key_names():
    """When a schema has specific property names, the prompt must list them
    explicitly so the model uses the exact keys, not human-readable variants."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.extract"]
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "severity": {"type": "string"},
            "service": {"type": "string"},
        },
        "required": ["category", "severity"],
    }
    prompt = runner._build_system_prompt(spec, "Extract fields", schema, {})

    # Must explicitly list the exact key names
    assert "category" in prompt
    assert "severity" in prompt
    assert "service" in prompt
    assert "Use EXACTLY these JSON keys" in prompt


def test_ai_op_prompt_surfaces_enum_constraints():
    """When a schema field has an enum, the prompt must list allowed values."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.route"]
    schema = {
        "type": "object",
        "properties": {
            "route": {
                "type": "string",
                "enum": ["ops", "security", "development"],
            },
        },
        "required": ["route"],
    }
    prompt = runner._build_system_prompt(spec, "Route incident", schema, {})

    assert "ops" in prompt
    assert "security" in prompt
    assert "development" in prompt
    assert "must be one of" in prompt.lower()


def test_ai_op_prompt_surfaces_numeric_bounds():
    """When a schema field has min/max bounds, the prompt must state them."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.score"]
    schema = {
        "type": "object",
        "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["score"],
    }
    prompt = runner._build_system_prompt(spec, "Score quality", schema, {})

    assert "range" in prompt.lower()
    assert "0" in prompt
    assert "1" in prompt


def test_ai_op_prompt_includes_grounding_rules():
    """The AI-op prompt must include anti-fabrication grounding rules."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.extract"]
    schema = {"type": "object", "properties": {"result": {"type": "string"}}}
    prompt = runner._build_system_prompt(spec, "Extract data", schema, {})

    assert "Do NOT invent" in prompt or "do not invent" in prompt.lower()
    assert "Do NOT rename keys" in prompt or "do not rename" in prompt.lower()


def test_ai_op_prompt_forbids_extra_keys():
    """The prompt must tell the model not to add extra keys beyond schema."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.extract"]
    schema = {
        "type": "object",
        "properties": {"result": {"type": "string"}},
        "required": ["result"],
    }
    prompt = runner._build_system_prompt(spec, "Extract", schema, {})

    assert "extra keys" in prompt.lower() or "add extra" in prompt.lower()


def test_ai_op_prompt_branches_enum_from_extras():
    """branches_enum in extras must appear as a constraint in the prompt."""
    runner = AIOperationsRunner.__new__(AIOperationsRunner)
    spec = AI_OPS["ai.route"]
    schema = spec.default_expect_schema
    extras = {"branches_enum": ["team_a", "team_b", "team_c"]}
    prompt = runner._build_system_prompt(spec, "Route to team", schema, extras)

    assert "team_a" in prompt
    assert "team_b" in prompt
    assert "team_c" in prompt
    assert "MUST choose exactly one" in prompt


# ---------------------------------------------------------------------------
# Verifier prompt grounding
# ---------------------------------------------------------------------------


def test_verifier_prompt_has_decision_policy():
    """The verifier prompt must include a structured decision policy."""
    # The system prompt is static (no runtime interpolation) — assert directly.
    prompt = VERIFIER_SYSTEM_PROMPT
    assert "Decision Policy" in prompt
    assert "Tool validity" in prompt
    assert "Required arguments" in prompt
    assert "Intent alignment" in prompt
    assert "Safety" in prompt


def test_verifier_prompt_requires_evidence_based_reasoning():
    """The verifier must reason only from provided evidence."""
    prompt = VERIFIER_SYSTEM_PROMPT
    assert "ONLY on the information below" in prompt or "Evidence Available" in prompt


def test_verifier_prompt_includes_credential_safety():
    """The verifier must check credential usage."""
    prompt = VERIFIER_SYSTEM_PROMPT
    assert "credential" in prompt.lower() or "secret" in prompt.lower()


# ---------------------------------------------------------------------------
# Critic prompt grounding
# ---------------------------------------------------------------------------


def test_critic_prompt_prioritizes_schema_conformance():
    """The critic must check schema conformance as the highest priority."""
    # The system prompt is static (no runtime interpolation) — assert directly.
    prompt = CRITIC_SYSTEM_PROMPT
    assert "Schema conformance" in prompt or "schema conformance" in prompt
    # Must call out the common failure mode of renamed keys
    assert "human-readable" in prompt.lower()


def test_critic_prompt_requires_evidence_based_reasoning():
    """The critic must reason only from provided evidence."""
    prompt = CRITIC_SYSTEM_PROMPT
    assert "Evidence Available" in prompt or "ONLY on the evidence" in prompt


# ---------------------------------------------------------------------------
# Tool spec improvements
# ---------------------------------------------------------------------------


def test_ai_tool_spec_extras_are_typed():
    """AI-op tool spec extras must have correct types, not all generic strings."""
    spec = AI_OPS["ai.route"]
    tool_spec = _create_ai_tool_spec("ai.route", spec)

    props = tool_spec["input_schema"]["properties"]
    assert props["branches_enum"]["type"] == "array"
    assert props["branches_enum"]["items"]["type"] == "string"


def test_ai_tool_spec_word_cap_is_integer():
    """word_cap must be typed as integer, not string."""
    spec = AI_OPS["ai.generate"]
    tool_spec = _create_ai_tool_spec("ai.generate", spec)

    props = tool_spec["input_schema"]["properties"]
    assert props["word_cap"]["type"] == "integer"


def test_ai_tool_spec_instruction_description_is_specific():
    """instruction parameter must have a specific description, not just 'Task instruction'."""
    spec = AI_OPS["ai.extract"]
    tool_spec = _create_ai_tool_spec("ai.extract", spec)

    desc = tool_spec["input_schema"]["properties"]["instruction"]["description"]
    assert "specific" in desc.lower() or "field names" in desc.lower()


# ---------------------------------------------------------------------------
# Planner prompt grounding
# ---------------------------------------------------------------------------


def test_planner_prompt_has_grounding_rules():
    """The planner prompt must include grounding rules against hallucination."""
    assert "Grounding Rules" in PLANNER_SYSTEM_PROMPT
    assert (
        "Do not fabricate" in PLANNER_SYSTEM_PROMPT
        or "never invent" in PLANNER_SYSTEM_PROMPT.lower()
    )


def test_planner_prompt_forbids_external_knowledge():
    """The planner must not use knowledge not in the provided context."""
    assert (
        "No external knowledge" in PLANNER_SYSTEM_PROMPT
        or "external knowledge" in PLANNER_SYSTEM_PROMPT.lower()
    )


def test_planner_prompt_requires_budget_compliance():
    """The planner must respect budget limits."""
    assert "budget" in PLANNER_SYSTEM_PROMPT.lower()
    assert (
        "exceed" in PLANNER_SYSTEM_PROMPT.lower()
        or "within budget" in PLANNER_SYSTEM_PROMPT.lower()
    )
