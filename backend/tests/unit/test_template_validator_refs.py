"""Template validator: multi-clause conditions and $secret validation.

Covers the greedy-$form-regex false positive and $secret-name validation
against declared credentials.uses.
"""

from saz.compiler.template_validator import validate_templates


def _spec(expr: str) -> dict:
    # A condition step is a realistic place for a compound expression.
    return {"steps": [{"id": "c", "type": "condition", "if": expr}]}


def test_multiclause_condition_no_false_form_warning():
    expr = (
        "{{ $form.budget > 0 && $form.budget < 5000 "
        "&& $step('extract').criticality == \"high\" }}"
    )
    warnings, errors = validate_templates(
        _spec(expr), form_fields=["budget"], step_ids=["extract", "c"]
    )
    assert errors == []
    assert not any("Unknown form field" in w for w in warnings), warnings


def test_unknown_form_field_still_warns():
    warnings, _ = validate_templates(
        _spec("{{ $form.bogus }}"), form_fields=["budget"], step_ids=["c"]
    )
    assert any("Unknown form field 'bogus'" in w for w in warnings), warnings


def test_unknown_secret_is_error():
    _, errors = validate_templates(
        _spec("{{ $secret('missing') }}"),
        form_fields=[],
        step_ids=["c"],
        credential_names=["known_api_key"],
    )
    assert any("Unknown secret 'missing'" in e for e in errors), errors


def test_known_secret_ok():
    _, errors = validate_templates(
        _spec("{{ $secret('known_api_key') }}"),
        form_fields=[],
        step_ids=["c"],
        credential_names=["known_api_key"],
    )
    assert errors == []


def test_secret_without_declared_credentials_warns():
    warnings, errors = validate_templates(
        _spec("{{ $secret('x') }}"),
        form_fields=[],
        step_ids=["c"],
        credential_names=[],
    )
    assert errors == []
    assert any(
        "no\n        credentials.uses".replace("\n        ", " ") in w
        or "credentials.uses are declared" in w
        for w in warnings
    ), warnings


def test_multiclause_step_refs_validated():
    # Both step refs must be checked; the second is unknown.
    expr = "{{ $step('a').x == 1 && $step('ghost').y == 2 }}"
    _, errors = validate_templates(_spec(expr), form_fields=[], step_ids=["a", "c"])
    assert any("Unknown step ID 'ghost'" in e for e in errors), errors
