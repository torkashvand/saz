"""Form field `widget` attribute (multi-line textarea support)."""

import pytest

from saz.compiler.dsl import compile_dsl

_BASE_STEPS = """
workflow:
  planner_mode: deterministic
  steps:
    - id: s1
      type: ai.extract
      description: d
      instruction: extract
      params:
        data:
          t: "{{ $form.notes }}"
      expect:
        type: object
        properties:
          a: { type: string }
        required: [a]
"""


def _yaml(field_block: str) -> str:
    return f"""
schema_version: 1
flow:
  name: widget_test
  description: widget test
form:
  fields:
{field_block}
{_BASE_STEPS}
"""


def test_textarea_widget_compiles_and_is_emitted_in_form_schema():
    yaml_text = _yaml(
        """    - name: notes
      type: text
      widget: textarea
"""
    )
    compiled = compile_dsl(yaml_text)
    assert compiled.warnings == []
    prop = compiled.form_schema["properties"]["notes"]
    assert prop["x-widget"] == "textarea"
    # widget is a presentation hint only — the data type stays string.
    assert prop["type"] in ("string", ["string", "null"])


def test_widget_on_non_string_field_is_rejected():
    yaml_text = _yaml(
        """    - name: count
      type: integer
      widget: textarea
"""
    )
    with pytest.raises(ValueError, match="widget"):
        compile_dsl(yaml_text)


def test_unknown_widget_value_is_rejected():
    yaml_text = _yaml(
        """    - name: notes
      type: text
      widget: fancybox
"""
    )
    with pytest.raises(ValueError):
        compile_dsl(yaml_text)
