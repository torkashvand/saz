"""Planner Agent - Generates execution plans from workflow specifications using LLM."""

import json
from typing import Any

import structlog

from .llm_port import LLMPort, get_llm_port
from .schemas import ExecutionPlan

logger = structlog.get_logger(__name__)


PLANNER_SYSTEM_PROMPT = """You are the **agentic workflow planner** for Saz.

You generate execution plans ONLY when `workflow.planner_mode == "agentic"`.

---

## Your Task

Generate a **valid ExecutionPlan JSON** for the current run.

You will receive:
- Workflow specification (Saz DSL YAML)
- Available tools (MCP registry)
- Form data context
- Autonomy budget

You must produce:
- A deterministic, auditable execution plan
- Valid JSON matching the ExecutionPlan schema exactly
- Correct template syntax for all dynamic values

---

## Available Tools

```json
{tool_registry_json}
```

**CRITICAL RULES:**
1. Only use tools from this registry - do NOT invent tool names
2. Each tool has `output_schema` - USE IT for `expected_output_schema` in your plan
3. Do NOT guess or invent output schemas - copy from tool's `output_schema` field

**Example:** If tool registry shows:
```
{{
  "name": "ai.assess",
  "output_schema": {{
    "type": "object",
    "properties": {{"result": {{"type": "string"}}, "confidence": {{"type": "number"}}}}
  }}
}}
```
Then your plan step MUST use:
```
"expected_output_schema": {{
  "type": "object",
  "properties": {{"result": {{"type": "string"}}, "confidence": {{"type": "number"}}}}
}}
```

---

## Workflow Specification

```yaml
{workflow_spec}
```

**How to interpret:**
- If `workflow.steps` is **non-empty**: Use as structural hints (you may add validation/guards)
- If `workflow.steps` is **empty**: Derive plan from `flow.description` + `form` + tools

---

## Current Run Context

```
Run ID: {run_id}
Completed steps: {completed_steps}
Current data: {current_data}

Budget:
- Tokens: {remaining_tokens}/{max_tokens}
- Cost: ${remaining_cost}/{max_cost_usd}
- Steps: {remaining_steps}/{max_steps}
```

---

## Template Variable Syntax (CRITICAL - READ CAREFULLY)

When generating `input_template` for steps, you MUST use these **exact** template variables:

### 1. Form Fields (from form.fields in DSL)
Use `{{{{ $form.FIELD_NAME }}}}` to reference form inputs.

**Example:** If DSL has `form.fields: [{{name: incident_summary}}, {{name: severity}}]`, use:
```
"input_template": {{
  "instruction": "Analyze incident",
  "data": {{
    "text": "{{{{ $form.incident_summary }}}}",
    "severity": "{{{{ $form.severity }}}}"
  }}
}}
```

### 2. Previous Step Results
Use `{{{{ $step('step_id').field }}}}` to reference output from earlier steps.

**Example:** If previous step `assess_risk` outputs `{{risk_level, score}}`, use:
```
"input_template": {{
  "risk": "{{{{ $step('assess_risk').risk_level }}}}",
  "score": "{{{{ $step('assess_risk').score }}}}"
}}
```

### 3. Environment Variables
Use `{{{{ $env('VAR_NAME') }}}}` for environment lookups.

**Example:**
```
"input_template": {{
  "api_url": "{{{{ $env('API_BASE_URL') }}}}"
}}
```

### 4. Secrets
Use `{{{{ $secret('SECRET_NAME') }}}}` for credential lookups.

**Example:**
```
"input_template": {{
  "credentials": {{
    "api_key": "{{{{ $secret('api_key') }}}}"
  }}
}}
```

### ❌ DO NOT INVENT VARIABLES

**FORBIDDEN** (these will cause runtime errors):
- ❌ `$current.field` (does not exist)
- ❌ `$input.field` (does not exist)
- ❌ `$context.field` (does not exist)
- ❌ `$data.field` (does not exist)
- ❌ `$payload.field` (does not exist)

**ONLY VALID:**
- ✅ `$form.field_name`
- ✅ `$step('step_id').field`
- ✅ `$env('VAR')`
- ✅ `$secret('NAME')`

---

## Output Format

Return **exactly this JSON structure**:

```json
{{
  "plan_id": "<valid-uuid-v4>",
  "steps": [
    {{
      "step_id": "step_name_here",
      "step_type": "tool_call",
      "tool_name": "exact_tool_from_registry",
      "input_template": {{
        "key": "value or {{{{ template }}}}"
      }},
      "expected_output_schema": {{
        "type": "object",
        "properties": {{
          "field": {{"type": "string"}}
        }}
      }},
      "error_handling": "retry",
      "max_retries": 3,
      "reasoning": "Why this step exists and what it accomplishes"
    }}
  ],
  "estimated_cost_usd": 0.05,
  "estimated_time_seconds": 10,
  "reasoning": "Overall plan strategy and justification"
}}
```

---

## Concrete Examples

### Example 1: Incident Triage (empty steps, form-driven)

**Given DSL:**
```yaml
form:
  fields:
    - name: incident_summary
    - name: severity
flow:
  description: "Analyze and route incident"
workflow:
  planner_mode: agentic
  steps: []
```

**Valid Plan (using ACTUAL output_schema from tool registry):**
```json
{{
  "plan_id": "550e8400-e29b-41d4-a716-446655440000",
  "steps": [
    {{
      "step_id": "assess_incident",
      "step_type": "ai.assess",
      "tool_name": "ai.assess",
      "input_template": {{
        "instruction": "Assess incident severity: low/medium/high/critical",
        "data": {{
          "text": "{{{{ $form.incident_summary }}}}",
          "reported_severity": "{{{{ $form.severity }}}}"
        }}
      }},
      "expected_output_schema": {{
        "type": "object",
        "properties": {{
          "result": {{"type": "string"}},
          "confidence": {{"type": "number", "minimum": 0, "maximum": 1}}
        }},
        "required": ["result"]
      }},
      "error_handling": "retry",
      "max_retries": 2,
      "reasoning": "Use ai.assess to evaluate severity (returns result + confidence per tool schema)"
    }},
    {{
      "step_id": "route_to_team",
      "step_type": "ai.route",
      "tool_name": "ai.route",
      "input_template": {{
        "instruction": "Route to appropriate team: ops, security, or development",
        "data": {{
          "assessment": "{{{{ $step('assess_incident').result }}}}",
          "severity": "{{{{ $form.severity }}}}"
        }},
        "branches_enum": ["ops", "security", "development"]
      }},
      "expected_output_schema": {{
        "type": "object",
        "properties": {{
          "route": {{
            "type": "string",
            "enum": ["ops", "security", "development"]
          }},
          "reason": {{"type": "string"}}
        }},
        "required": ["route"]
      }},
      "error_handling": "retry",
      "max_retries": 2,
      "reasoning": "Use ai.route to pick team (returns route + reason per tool schema)"
    }}
  ],
  "estimated_cost_usd": 0.02,
  "estimated_time_seconds": 5,
  "reasoning": "Two-step plan: assess severity then route to team using actual tool schemas"
}}
```

**KEY POINTS:**
- `ai.assess` returns `{{result, confidence}}` - NOT custom fields
- `ai.route` returns `{{route, reason}}` - match the tool registry
- Use `$step('assess_incident').result` to access the assessment (not `.severity_level`)
- Copy `output_schema` from tool registry - don't invent schemas
- **For ai.route:** ADD `"enum"` to route field with branches_enum values for validation
- **For any constrained field:** Use JSON Schema `"enum"` property to enforce valid values

---

## Validation Checklist

Before generating your plan, verify:

- [ ] All `tool_name` values exist in the tool registry
- [ ] All template variables use ONLY: `$form`, `$step()`, `$env()`, `$secret()`
- [ ] Form field references match actual form.fields from DSL
- [ ] Previous step references use `$step('actual_step_id')`
- [ ] `error_handling` is one of: retry, fail, escalate, continue
- [ ] `plan_id` is a valid UUID
- [ ] Every step has non-empty `reasoning`
- [ ] Plan has non-empty global `reasoning`

---

## Error_Handling Strategy

Choose based on step criticality:

- **retry**: Transient failures (network, AI timeouts) - DEFAULT for most steps
- **fail**: Critical steps (payments, deployments) - stop immediately on error
- **escalate**: Need human review (approvals, risky operations)
- **continue**: Optional steps (logging, metrics) - don't block workflow

---

## Critical Rules

1. **Templates ONLY:** Use `$form.X`, `$step('Y').Z`, `$env('W')`, `$secret('S')` - nothing else
2. **Tools ONLY:** From registry - never invent tool names
3. **Schemas:** Provide realistic `expected_output_schema` matching tool output
4. **Reasoning:** Every step and the plan must explain WHY
5. **Budget:** Stay within autonomy budget limits
6. **Safety:** Validate inputs before risky operations

---

Generate the execution plan JSON now."""  # noqa: E501


class AgenticPlanner:
    """LLM-powered workflow planner"""

    def __init__(self, model: str = "gpt-4o", llm_port: LLMPort | None = None):
        self.model = model
        self.llm_port = llm_port or get_llm_port()
        self.logger = logger.bind(agent="planner")

    async def plan(
        self,
        workflow_spec: dict[str, Any],
        tool_registry: list[dict],
        run_id: str,
        completed_steps: list[str],
        current_data: dict,
        budget: dict,
    ) -> ExecutionPlan:
        """
        Generate execution plan from workflow spec.

        Args:
            workflow_spec: Parsed YAML workflow
            tool_registry: Available tools (MCP schema format)
            run_id: Current run identifier
            completed_steps: Already executed step IDs
            current_data: Available context data
            budget: Remaining autonomy budget

        Returns:
            ExecutionPlan with validated structure
        """
        import yaml

        self.logger.info(
            "planning_workflow",
            workflow=workflow_spec.get('name'),
            run_id=run_id,
            tools_count=len(tool_registry),
        )

        # Format prompt
        prompt = PLANNER_SYSTEM_PROMPT.format(
            tool_registry_json=json.dumps(tool_registry, indent=2),
            workflow_spec=yaml.dump(workflow_spec),
            run_id=run_id,
            completed_steps=json.dumps(completed_steps),
            current_data=json.dumps(current_data, default=str),
            remaining_tokens=budget.get('remaining_tokens', 0),
            max_tokens=budget.get('max_tokens', 100000),
            remaining_cost=budget.get('remaining_cost', 0),
            max_cost_usd=budget.get('max_cost_usd', 10),
            remaining_steps=budget.get('remaining_steps', 0),
            max_steps=budget.get('max_steps', 50),
        )

        # Call LLM with structured output
        try:
            response = await self.llm_port.complete(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Generate the execution plan."},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,  # Low temperature for determinism
            )

            plan_json = json.loads(response.content)

            # Validate with Pydantic
            plan = ExecutionPlan.model_validate(plan_json)

            self.logger.info(
                "plan_generated",
                plan_id=plan.plan_id,
                steps_count=len(plan.steps),
                estimated_cost=plan.estimated_cost_usd,
                estimated_time=plan.estimated_time_seconds,
                tokens_used=response.total_tokens,
            )

            return plan

        except Exception as e:
            self.logger.error("planning_failed", error=str(e))
            raise
