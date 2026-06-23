"""conditions rule: if/when expressions parse and reference in-scope vars."""

from saz.linter.context import LintContext
from saz.linter.findings import LintCode
from saz.linter.rules.conditions import ConditionsRule


def _ctx(steps, form_fields=()):
    return LintContext.from_dsl(
        {
            "form": {"fields": [{"name": n} for n in form_fields]},
            "workflow": {"steps": steps},
        }
    )


def _codes(findings):
    return {f.code for f in findings}


def test_valid_condition_clean():
    ctx = _ctx(
        [{"id": "c", "type": "condition", "if": "$form.budget > 0 && $form.ok == 'yes'"}],
        form_fields=["budget", "ok"],
    )
    assert ConditionsRule().check(ctx) == []


def test_unknown_form_var():
    ctx = _ctx(
        [{"id": "c", "type": "condition", "if": "$form.missing > 0"}],
        form_fields=["budget"],
    )
    assert LintCode.CONDITION_UNKNOWN_VAR in _codes(ConditionsRule().check(ctx))


def test_forward_step_ref_in_condition():
    ctx = _ctx(
        [
            {"id": "c", "type": "condition", "if": "$step('later').x == 'y'"},
            {"id": "later", "type": "ai.generate", "instruction": "hi"},
        ],
    )
    assert LintCode.CONDITION_UNKNOWN_VAR in _codes(ConditionsRule().check(ctx))


def test_arithmetic_flagged():
    ctx = _ctx(
        [{"id": "c", "type": "condition", "if": "$form.a + 1 > 2"}],
        form_fields=["a"],
    )
    assert LintCode.CONDITION_ARITHMETIC in _codes(ConditionsRule().check(ctx))


def test_parse_error_flagged():
    ctx = _ctx(
        [{"id": "c", "type": "condition", "if": "$form.a =="}],
        form_fields=["a"],
    )
    assert LintCode.CONDITION_PARSE_ERROR in _codes(ConditionsRule().check(ctx))


def test_when_guard_checked():
    ctx = _ctx(
        [{"id": "s", "type": "ai.generate", "instruction": "hi", "when": "$form.go == 'x'"}],
        form_fields=["other"],
    )
    assert LintCode.CONDITION_UNKNOWN_VAR in _codes(ConditionsRule().check(ctx))


def test_env_and_secret_always_in_scope():
    ctx = _ctx(
        [{"id": "c", "type": "condition", "if": "$env('X') == 'y' || $secret('K') != ''"}],
    )
    assert ConditionsRule().check(ctx) == []
