"""template_refs rule: form-field and step references must resolve."""

from saz.linter.context import LintContext
from saz.linter.findings import LintCode
from saz.linter.rules.template_refs import TemplateRefsRule


def _ctx(steps, form_fields=()):
    dsl = {
        "form": {"fields": [{"name": n} for n in form_fields]},
        "workflow": {"steps": steps},
    }
    return LintContext.from_dsl(dsl)


def _codes(findings):
    return {f.code for f in findings}


def test_unknown_form_field_flagged():
    ctx = _ctx(
        [{"id": "a", "type": "ai.generate", "instruction": "Use {{ $form.missing }}"}],
        form_fields=["present"],
    )
    findings = TemplateRefsRule().check(ctx)
    assert LintCode.TEMPLATE_REF_UNKNOWN_FORM_FIELD in _codes(findings)


def test_known_form_field_clean():
    ctx = _ctx(
        [{"id": "a", "type": "ai.generate", "instruction": "Use {{ $form.present }}"}],
        form_fields=["present"],
    )
    assert TemplateRefsRule().check(ctx) == []


def test_unknown_step_flagged():
    ctx = _ctx(
        [{"id": "a", "type": "ai.generate", "instruction": "{{ $step('nope') }}"}],
    )
    findings = TemplateRefsRule().check(ctx)
    assert LintCode.TEMPLATE_REF_UNKNOWN_STEP in _codes(findings)


def test_forward_step_reference_flagged():
    # step 'a' references 'b' which runs later
    ctx = _ctx(
        [
            {"id": "a", "type": "ai.generate", "instruction": "{{ $step('b') }}"},
            {"id": "b", "type": "ai.generate", "instruction": "hi"},
        ],
    )
    findings = TemplateRefsRule().check(ctx)
    assert LintCode.TEMPLATE_REF_FORWARD_STEP in _codes(findings)


def test_backward_step_reference_clean():
    ctx = _ctx(
        [
            {"id": "a", "type": "ai.generate", "instruction": "hi"},
            {"id": "b", "type": "ai.generate", "instruction": "{{ $step('a').x }}"},
        ],
    )
    assert TemplateRefsRule().check(ctx) == []


def test_self_reference_is_forward():
    ctx = _ctx(
        [{"id": "a", "type": "ai.generate", "instruction": "{{ $step('a') }}"}],
    )
    findings = TemplateRefsRule().check(ctx)
    assert LintCode.TEMPLATE_REF_FORWARD_STEP in _codes(findings)
