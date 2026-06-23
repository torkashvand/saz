"""ai_prose_schema rule: prose list-size bounds vs expect schema.

Includes the exact regression from change_approval_ansible.
"""

from saz.linter.context import LintContext
from saz.linter.findings import LintCode
from saz.linter.rules.ai_prose_schema import AiProseSchemaRule


def _ctx(instruction, expect):
    dsl = {
        "workflow": {
            "steps": [
                {
                    "id": "summarize",
                    "type": "ai.extract",
                    "instruction": instruction,
                    "expect": expect,
                }
            ]
        }
    }
    return LintContext.from_dsl(dsl)


def _schema(pre_checks_schema):
    return {
        "type": "object",
        "properties": {"pre_checks": pre_checks_schema},
    }


def test_regression_prose_3_6_vs_minitems_1():
    instruction = (
        "Rules:\n" '- "pre_checks" is a short ordered list (3-6 items) of things to verify.\n'
    )
    ctx = _ctx(instruction, _schema({"type": "array", "items": {"type": "string"}, "minItems": 1}))
    findings = AiProseSchemaRule().check(ctx)
    assert len(findings) == 1
    f = findings[0]
    assert f.code is LintCode.PROSE_SCHEMA_COUNT_MISMATCH
    assert f.field == "expect.pre_checks"
    assert f.severity.value == "error"


def test_fixed_schema_is_clean():
    instruction = '- "pre_checks" must be a list of EXACTLY 3 to 6 distinct items.\n'
    ctx = _ctx(
        instruction,
        _schema({"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 6}),
    )
    assert AiProseSchemaRule().check(ctx) == []


def test_no_quantifier_no_finding():
    instruction = '- "pre_checks" is an ordered list of things to verify.\n'
    ctx = _ctx(instruction, _schema({"type": "array", "items": {"type": "string"}, "minItems": 1}))
    assert AiProseSchemaRule().check(ctx) == []


def test_at_least_pattern_against_unset_min():
    instruction = '- "pre_checks" must contain at least 3 items.\n'
    ctx = _ctx(instruction, _schema({"type": "array", "items": {"type": "string"}}))
    findings = AiProseSchemaRule().check(ctx)
    assert [f.code for f in findings] == [LintCode.PROSE_SCHEMA_COUNT_MISMATCH]


def test_up_to_pattern_against_unbounded_max():
    instruction = '- "pre_checks" should list up to 6 items.\n'
    ctx = _ctx(instruction, _schema({"type": "array", "items": {"type": "string"}, "minItems": 1}))
    findings = AiProseSchemaRule().check(ctx)
    assert [f.code for f in findings] == [LintCode.PROSE_SCHEMA_COUNT_MISMATCH]


def test_ambiguous_two_array_fields_in_one_bullet_skipped():
    # precision guard: two array fields named in one bullet → no association
    instruction = '- "pre_checks" and "affected_targets" together: 3-6 items.\n'
    expect = {
        "type": "object",
        "properties": {
            "pre_checks": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "affected_targets": {"type": "array", "items": {"type": "string"}},
        },
    }
    ctx = _ctx(instruction, expect)
    assert AiProseSchemaRule().check(ctx) == []


def test_non_ai_step_ignored():
    dsl = {
        "workflow": {
            "steps": [
                {
                    "id": "t",
                    "type": "tool.call",
                    "tool": "http_request",
                    "instruction": '"pre_checks" 3-6 items',
                    "expect": _schema({"type": "array", "minItems": 1}),
                }
            ]
        }
    }
    ctx = LintContext.from_dsl(dsl)
    assert AiProseSchemaRule().check(ctx) == []
