"""Tests for template expression validator."""

from saz.compiler.template_validator import validate_templates


def test_valid_step_reference():
    """Test valid step reference without .output."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": {"value": "{{ $step('step0').category }}"}},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step0", "step1"])

    assert len(errors) == 0
    assert len(warnings) == 0


def test_invalid_step_reference_with_output_field():
    """Test that .output.field is detected as error."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": {"value": "{{ $step('step0').output.category }}"}},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step0", "step1"])

    assert len(errors) == 1
    assert ".output." in errors[0]
    assert "automatically access" in errors[0]
    assert "$step('step0').category" in errors[0]


def test_unnecessary_output_access():
    """Test that bare .output generates warning."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": "{{ $step('step0').output }}"},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step0", "step1"])

    assert len(errors) == 0
    assert len(warnings) == 1
    assert "Unnecessary '.output'" in warnings[0]


def test_unknown_step_id():
    """Test that unknown step IDs are detected."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": "{{ $step('unknown_step').field }}"},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step1"])

    assert len(errors) == 1
    assert "Unknown step ID 'unknown_step'" in errors[0]


def test_valid_form_reference():
    """Test valid form field reference."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": "{{ $form.email }}"},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, ["email", "name"], ["step1"])

    assert len(errors) == 0
    assert len(warnings) == 0


def test_unknown_form_field():
    """Test that unknown form fields generate warnings."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {"data": "{{ $form.unknown_field }}"},
            }
        ]
    }

    warnings, errors = validate_templates(workflow, ["email"], ["step1"])

    assert len(errors) == 0
    assert len(warnings) == 1
    assert "Unknown form field" in warnings[0]


def test_env_and_secret_references_allowed():
    """Test that $env and a declared $secret don't generate errors/warnings."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {
                    "env_var": "{{ $env('API_URL') }}",
                    "secret": "{{ $secret('api_key') }}",
                },
            }
        ]
    }

    # A $secret is validated against declared credentials.uses; declare it so
    # the reference is recognized and produces no warning.
    warnings, errors = validate_templates(workflow, [], ["step1"], credential_names=["api_key"])

    assert len(errors) == 0
    assert len(warnings) == 0


def test_undeclared_secret_warns():
    """A $secret with no matching credentials.uses is flagged, not silent."""
    workflow = {"steps": [{"id": "s", "params": {"secret": "{{ $secret('api_key') }}"}}]}
    warnings, errors = validate_templates(workflow, [], ["s"])
    assert errors == []
    assert any("api_key" in w for w in warnings), warnings


def test_multiple_errors_in_workflow():
    """Test detection of multiple template errors."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {
                    "cat": "{{ $step('step0').output.category }}",
                    "pri": "{{ $step('step0').output.priority }}",
                    "sent": "{{ $step('unknown').sentiment }}",
                },
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step0", "step1"])

    assert len(errors) == 3
    assert any(".output.category" in e for e in errors)
    assert any(".output.priority" in e for e in errors)
    assert any("unknown_step" in e.lower() or "Unknown step" in e for e in errors)


def test_nested_templates_in_lists():
    """Test validation works with nested structures."""
    workflow = {
        "steps": [
            {
                "id": "step1",
                "params": {
                    "items": [
                        "{{ $step('step0').output.field1 }}",
                        "{{ $step('step0').field2 }}",
                    ]
                },
            }
        ]
    }

    warnings, errors = validate_templates(workflow, [], ["step0", "step1"])

    assert len(errors) == 1
    assert ".output.field1" in errors[0]


def test_complex_real_world_example():
    """Test validation on realistic workflow."""
    workflow = {
        "steps": [
            {
                "id": "extract",
                "type": "ai.extract",
                "params": {"data": {"text": "{{ $form.ticket_text }}"}},
            },
            {
                "id": "route",
                "type": "ai.route",
                "params": {
                    "data": {
                        "category": "{{ $step('extract').output.category }}",  # ERROR
                        "priority": "{{ $step('extract').priority }}",  # OK
                    }
                },
            },
        ]
    }

    warnings, errors = validate_templates(workflow, ["ticket_text"], ["extract", "route"])

    assert len(errors) == 1
    assert ".output.category" in errors[0]
    assert "$step('extract').category" in errors[0]
