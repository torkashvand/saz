"""tool_params rule: validate tool.call params against the tool input schema."""

import pytest

from saz.linter.context import LintContext
from saz.linter.findings import LintCode
from saz.linter.rules.tool_params import ToolParamsRule

_SPEC = {
    "name": "demo_tool",
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "url": {"type": "string"},
            "retries": {"type": "integer"},
            "mode": {"type": "string", "enum": ["check", "apply"]},
        },
        "required": ["url", "mode"],
    },
}


class _FakeRegistry:
    def get_tool_spec(self, name):
        return _SPEC if name == "demo_tool" else None


@pytest.fixture(autouse=True)
def _registry(monkeypatch):
    monkeypatch.setattr("saz.globals.get_tool_registry", lambda: _FakeRegistry())


def _ctx(params):
    step = {"id": "t", "type": "tool.call", "tool": "demo_tool", "params": params}
    return LintContext.from_dsl({"workflow": {"steps": [step]}})


def _codes(findings):
    return {f.code for f in findings}


def test_valid_params_clean():
    findings = ToolParamsRule().check(_ctx({"url": "http://x", "mode": "check"}))
    assert findings == []


def test_missing_required():
    findings = ToolParamsRule().check(_ctx({"url": "http://x"}))
    assert LintCode.TOOL_PARAMS_MISSING_REQUIRED in _codes(findings)


def test_unknown_key_when_closed():
    findings = ToolParamsRule().check(_ctx({"url": "http://x", "mode": "check", "bogus": 1}))
    assert LintCode.TOOL_PARAMS_UNKNOWN_KEY in _codes(findings)


def test_type_mismatch_literal():
    findings = ToolParamsRule().check(
        _ctx({"url": "http://x", "mode": "check", "retries": "three"})
    )
    assert LintCode.TOOL_PARAMS_TYPE_MISMATCH in _codes(findings)


def test_enum_violation_literal():
    findings = ToolParamsRule().check(_ctx({"url": "http://x", "mode": "destroy"}))
    assert LintCode.TOOL_PARAMS_TYPE_MISMATCH in _codes(findings)


def test_templated_value_skips_type_check():
    findings = ToolParamsRule().check(
        _ctx({"url": "http://x", "mode": "{{ $form.mode }}", "retries": "{{ $form.n }}"})
    )
    assert findings == []


def test_registry_uninitialized_skips(monkeypatch):
    def _raise():
        raise RuntimeError("globals not initialized")

    monkeypatch.setattr("saz.globals.get_tool_registry", _raise)
    assert ToolParamsRule().check(_ctx({"url": "http://x", "mode": "check"})) == []
