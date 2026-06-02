"""
Test that all unified DSL templates compile successfully.

This test discovers all YAML templates in saz/examples/unified/ and validates
that each one compiles without errors using compile_dsl().
"""

from pathlib import Path

import pytest

from saz.compiler import compile_dsl
from saz.examples import get_template_manager


def discover_templates():
    """Discover all YAML template files."""
    templates_dir = Path(__file__).parent.parent.parent / "saz" / "examples" / "unified"
    return list(templates_dir.glob("*.yaml"))


@pytest.mark.parametrize("template_path", discover_templates())
def test_template_compiles(template_path):
    """Each template compiles as-is — including its top-level meta block —
    through the same compiler the API uses, no string stripping required."""
    yaml_content = template_path.read_text(encoding='utf-8')

    try:
        compiled = compile_dsl(yaml_content)
        assert compiled is not None
        assert compiled.flow_name is not None
        assert len(compiled.workflow_spec.get("steps", [])) > 0
    except Exception as e:
        pytest.fail(f"Template {template_path.name} failed to compile: {str(e)}")


def test_all_templates_discovered():
    """Ensure we found at least the expected templates."""
    templates = discover_templates()
    template_names = [t.stem for t in templates]

    # Expected templates based on proposal
    expected = [
        "minimal_ai_step",
        "support_ticket_webhook",
        "incident_triage",
        "change_approval_ansible",
        "callback_driven_maintenance",
        "http_summary_report",
        "pii_safe_support_demo",
    ]

    for name in expected:
        assert name in template_names, f"Expected template '{name}' not found"

    assert len(templates) >= len(
        expected
    ), f"Expected at least {len(expected)} templates, found {len(templates)}"


def test_template_manager_loads_all():
    """Test that TemplateManager loads all templates successfully."""
    manager = get_template_manager()
    templates = manager.list_templates()

    # Should load all valid templates
    assert len(templates) >= 7, f"Expected at least 7 templates, got {len(templates)}"

    # All templates should have valid metadata
    for t in templates:
        assert t.metadata.id is not None
        assert t.metadata.title is not None
        assert t.metadata.complexity in ["beginner", "medium", "advanced"]
        assert isinstance(t.metadata.recommended, bool)
        assert t.compiled is not None


def test_recommended_templates():
    """Test that recommended templates are properly flagged."""
    manager = get_template_manager()
    recommended = manager.list_recommended()

    # Should have at least some recommended templates
    assert len(recommended) >= 3, "Expected at least 3 recommended templates"

    # All recommended templates should have recommended=True
    for t in recommended:
        assert t.metadata.recommended is True
