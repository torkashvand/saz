from pathlib import Path

from saz.compiler.dsl import compile_dsl
from saz.policies.policy_engine import PolicyEngine

_YAML = (
    Path(__file__).resolve().parents[2] / "saz" / "examples" / "unified" / "rfq_rfp_drafting.yaml"
)


def _compiled():
    return compile_dsl(_YAML.read_text())


def _steps():
    return {s["id"]: s for s in _compiled().workflow_spec["steps"]}


def test_compiles_without_warnings():
    assert _compiled().warnings == []


def test_has_budget_gate_with_valid_grammar():
    # The condition grammar has no arithmetic, so the deterministic gate covers
    # the money caps only (comparisons). Weight-sum consistency is checked by
    # validate_inputs and surfaced to the reviewer.
    gate = _steps()["gate_budget"]
    assert gate["type"] == "condition"
    expr = gate["if"]
    assert "20000" in expr and "10000" in expr and "100000" in expr
    assert "+" not in expr, "condition grammar has no arithmetic operator"
    validate_instruction = _steps()["validate_inputs"]["instruction"]
    assert "sum to 100" in validate_instruction  # weight-sum checked here instead


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


def test_budget_gate_actually_blocks_downstream_via_when_guards():
    # A `condition` step does not halt the workflow on its own; downstream steps
    # must carry a `when:` guard referencing the gate result to be blocked.
    steps = _steps()
    gated = [
        "pont_check",
        "draft_narrative",
        "procurement_review",
        "render_draft",
        "procurement_signoff",
        "project_signoff",
        "render_final",
        "audit_record",
    ]
    for sid in gated:
        guard = steps[sid].get("when") or ""
        assert "gate_budget" in guard, f"{sid} must be guarded by the budget gate (when:)"


def test_market_consultation_feeds_the_final_document():
    # The incorporated narrative (after supplier feedback) must reach the FINAL
    # render, not be discarded. render_final reads a single finalized source.
    steps = _steps()
    assert (
        "incorporate_feedback" not in steps
    ), "incorporate_feedback was renamed to finalize_narrative"
    finalize = steps["finalize_narrative"]
    finalize_inputs = str(finalize.get("params", {}).get("data", {}))
    assert "supplier_feedback" in finalize_inputs
    assert "draft_narrative" in finalize_inputs
    final_values = str(steps["render_final"]["params"]["values"])
    assert "finalize_narrative" in final_values
    assert "draft_narrative" not in final_values


def test_docx_render_is_allowed_under_pii_policy():
    # Under pii.allow:false the render values carry the contact person's email
    # and phone (intended document content) — docx_render must be allow-listed
    # for exactly those paths or every render is blocked.
    compiled = _compiled()
    pe = PolicyEngine()
    pe.initialize_from_dsl("run-pii", compiled.policies)
    args = {
        "template": "saz/examples/templates/rfq_template.docx",
        "output_name": "rfq_draft_T88815",
        "require_all": False,
        "values": {
            "contact_name": "Badreddine Ajbar El Gueriri",
            "contact_email": "badre.ajbar@geant.org",
            "contact_phone": "+31 6 29003633",
            "objective": "Find a modern HR system.",
        },
    }
    allowed, reason = pe.check_tool_call(tool_name="docx_render", arguments=args, run_id="run-pii")
    assert allowed, f"docx_render blocked by PII policy: {reason}"
