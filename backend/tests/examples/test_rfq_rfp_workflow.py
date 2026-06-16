from pathlib import Path

from saz.compiler.dsl import compile_dsl

_YAML = (
    Path(__file__).resolve().parents[2] / "saz" / "examples" / "unified" / "rfq_rfp_drafting.yaml"
)


def _compiled():
    return compile_dsl(_YAML.read_text())


def _steps():
    return {s["id"]: s for s in _compiled().workflow_spec["steps"]}


def test_compiles_without_warnings():
    assert _compiled().warnings == []


def test_has_budget_and_weight_gate():
    gate = _steps()["gate_budget"]
    assert gate["type"] == "condition"
    expr = gate["if"]
    assert "20000" in expr and "10000" in expr and "100000" in expr
    assert "== 100" in expr  # weight-sum checks


def test_dual_signoff_and_render_steps_present():
    steps = _steps()
    assert steps["procurement_signoff"]["type"] == "human.approval"
    assert steps["project_signoff"]["type"] == "human.approval"
    assert steps["render_draft"]["tool"] == "docx_render"
    assert steps["render_final"]["tool"] == "docx_render"
    assert steps["render_final"]["params"]["require_all"] is True


def test_ai_steps_have_strict_expect():
    for sid in ("validate_inputs", "pont_check", "draft_narrative"):
        step = _steps()[sid]
        expect = step["expect"]
        assert expect["type"] == "object"
        assert expect["required"], f"{sid} must declare required fields"
