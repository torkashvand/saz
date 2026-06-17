"""Regression for the AI-output -> template seam.

The bug: ai.generate (text op) returns its content as a STRING under 'output',
so $step(id).<field> resolves empty. ai.extract (JSON op) returns a dict that
the executor unwraps, so the fields are addressable. This pins that contract.
"""

from saz.engine.executor import _unwrap_ai_output
from saz.engine.templating import TemplateContext


def _ctx(step_output):
    return TemplateContext(
        form_data={},
        step_results={"s": {"output": step_output}},
        secret_resolver=lambda name: None,
    )


def test_extract_fields_are_addressable_generate_fields_are_not():
    extract_result = {
        "output": {"objective": "Find a modern HRIS"},
        "usage": {"tokens": 1},
        "metadata": {"op": "ai.extract"},
    }
    generate_result = {
        "output": '{"objective": "Find a modern HRIS"}',  # a JSON *string*, not a dict
        "usage": {"tokens": 1},
        "metadata": {"op": "ai.generate"},
    }

    ex = _unwrap_ai_output("ai.extract", extract_result)
    gen = _unwrap_ai_output("ai.generate", generate_result)

    # ai.extract: envelope unwrapped to the dict -> fields addressable
    assert ex == {"objective": "Find a modern HRIS"}
    assert _ctx(ex).resolve("{{ $step('s').objective }}") == "Find a modern HRIS"

    # ai.generate: stays wrapped (content is a string) -> .objective cannot resolve
    assert gen == generate_result
    assert _ctx(gen).resolve("{{ $step('s').objective }}") != "Find a modern HRIS"
