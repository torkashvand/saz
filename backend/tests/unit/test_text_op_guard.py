"""Compiler guard: text AI ops (generate/summarize/translate) return a single
string under 'output' and must not declare a structured expect schema."""

import pytest

from saz.compiler.dsl import compile_dsl

_STEPS_TAIL = """
"""


def _yaml(step_block: str) -> str:
    return f"""
schema_version: 1
flow:
  name: textop
  description: text op guard test
workflow:
  planner_mode: deterministic
  steps:
{step_block}
"""


def test_text_op_with_structured_expect_is_rejected():
    # ai.generate cannot promise background/objective/scope — that was the bug.
    yaml_text = _yaml(
        """    - id: draft
      type: ai.generate
      description: draft prose
      instruction: write background, objective, scope
      expect:
        type: object
        properties:
          background: { type: string }
          objective: { type: string }
          scope: { type: string }
        required: [background, objective, scope]
"""
    )
    with pytest.raises(ValueError, match="text operation"):
        compile_dsl(yaml_text)


def test_text_op_with_output_only_expect_is_allowed():
    yaml_text = _yaml(
        """    - id: draft
      type: ai.generate
      description: draft prose
      instruction: write a paragraph
      expect:
        type: object
        properties:
          output: { type: string }
        required: [output]
"""
    )
    compiled = compile_dsl(yaml_text)
    assert compiled.warnings == []


def test_structured_op_with_structured_expect_is_allowed():
    # ai.extract is a JSON op — structured fields are exactly its job.
    yaml_text = _yaml(
        """    - id: draft
      type: ai.extract
      description: structured narrative
      instruction: produce background, objective, scope
      expect:
        type: object
        properties:
          background: { type: string }
          objective: { type: string }
          scope: { type: string }
        required: [background, objective, scope]
"""
    )
    compiled = compile_dsl(yaml_text)
    assert compiled.warnings == []
