"""Wedge-demo verification tests.

These tests pin down the safety- and demo-critical properties of the three
wedge-demo workflows:

  * incident_triage              — AI-assisted classification + audit artifact
  * change_approval_ansible      — AI risk summary → Ansible check → approval → apply
  * callback_driven_maintenance  — webhook.wait suspension + external callback

They are intentionally narrow: each test asserts one demo-critical invariant
that a regression would silently break (e.g. an AI step losing its strict
`expect` schema, or the change demo skipping the approval gate).

For end-to-end suspend/resume and webhook callback behaviour, see
`tests/integration/test_approval_workflow.py` and
`tests/api/test_webhook_callback_api.py` — these wedge tests cover the
WORKFLOW STRUCTURE; the integration suites cover the RUNTIME BEHAVIOUR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from saz.compiler import compile_dsl
from saz.examples import get_template_manager

UNIFIED_DIR = Path(__file__).parent.parent.parent / "saz" / "examples" / "unified"
ANSIBLE_DIR = Path(__file__).parent.parent.parent / "saz" / "examples" / "ansible"

WEDGE_DEMO_IDS = (
    "incident_triage",
    "change_approval_ansible",
    "callback_driven_maintenance",
)


def _strip_meta(yaml_content: str) -> str:
    """Remove the meta section the way TemplateManager does."""
    if "meta:" not in yaml_content:
        return yaml_content
    out: list[str] = []
    in_meta = False
    for line in yaml_content.splitlines():
        if line.strip().startswith("meta:"):
            in_meta = True
            continue
        if in_meta:
            if line and not line.startswith((" ", "\t")):
                in_meta = False
            else:
                continue
        if not in_meta:
            out.append(line)
    return "\n".join(out)


def _load_compiled(demo_id: str):
    path = UNIFIED_DIR / f"{demo_id}.yaml"
    return compile_dsl(_strip_meta(path.read_text(encoding="utf-8")))


def _load_meta(demo_id: str) -> dict:
    path = UNIFIED_DIR / f"{demo_id}.yaml"
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parsed.get("meta", {})


# -------------------------------------------------------------------------------------- #
# Common: all three demos compile, advertise the wedge-demo tag, are recommended         #
# -------------------------------------------------------------------------------------- #


@pytest.mark.parametrize("demo_id", WEDGE_DEMO_IDS)
def test_wedge_demo_compiles_clean(demo_id):
    """Each wedge demo must compile without warnings or template errors."""
    compiled = _load_compiled(demo_id)
    assert (
        compiled.flow_name == demo_id
    ), f"flow.name must match meta.id for {demo_id}; got {compiled.flow_name}"
    # Demo files are conference-ready: zero template warnings means no
    # silently-empty $step / $env references.
    assert (
        compiled.warnings == []
    ), f"{demo_id} should compile without template warnings; got {compiled.warnings}"


@pytest.mark.parametrize("demo_id", WEDGE_DEMO_IDS)
def test_wedge_demo_is_tagged_and_recommended(demo_id):
    """The three demos must surface as recommended wedge demos in the
    template list — operators rely on this to find them."""
    meta = _load_meta(demo_id)
    assert meta.get("recommended") is True, (
        f"{demo_id} must be marked recommended: true so the templates API "
        f"surfaces it under recommended_only=true"
    )
    tags = meta.get("tags", [])
    assert "wedge-demo" in tags, (
        f"{demo_id} must carry the 'wedge-demo' tag so the demos can be "
        f"filtered together in the UI/API"
    )


def test_wedge_demos_visible_via_template_manager():
    """All three wedge demos must be loaded by the global TemplateManager."""
    mgr = get_template_manager()
    loaded = {t.metadata.id for t in mgr.list_templates()}
    for demo_id in WEDGE_DEMO_IDS:
        assert demo_id in loaded, (
            f"TemplateManager did not load {demo_id} — check the YAML "
            f"compiles and the meta block is well-formed"
        )

    recommended = {t.metadata.id for t in mgr.list_recommended()}
    for demo_id in WEDGE_DEMO_IDS:
        assert demo_id in recommended, f"{demo_id} must appear in list_recommended()"


@pytest.mark.parametrize("demo_id", WEDGE_DEMO_IDS)
def test_wedge_demo_ai_steps_have_strict_expect(demo_id):
    """Every AI step in a wedge demo must carry a strict `expect` schema with
    a `required` list. The whole "AI proposes, runtime enforces" wedge
    depends on this — without `required`, the model can return wrong keys
    and the runtime will accept them."""
    compiled = _load_compiled(demo_id)
    ai_steps = [s for s in compiled.workflow_spec["steps"] if s["type"].startswith("ai.")]
    assert ai_steps, f"{demo_id} should exercise at least one AI step"
    for step in ai_steps:
        expect = step.get("expect")
        assert isinstance(
            expect, dict
        ), f"{demo_id} step {step['id']} must declare an expect schema"
        assert (
            expect.get("type") == "object"
        ), f"{demo_id} step {step['id']} expect schema must be type=object"
        assert expect.get("required"), (
            f"{demo_id} step {step['id']} expect schema must declare a "
            f"non-empty required list so the runtime validator rejects "
            f"missing fields"
        )


# -------------------------------------------------------------------------------------- #
# incident_triage                                                                        #
# -------------------------------------------------------------------------------------- #


def test_incident_triage_is_safe_by_default():
    """Incident triage must NOT mutate external systems. The only
    deterministic post-AI step is artifact.store — there must be no
    tool.call or webhook.wait that would touch a real production system,
    and no human.approval (incident triage is informational, not a gate)."""
    compiled = _load_compiled("incident_triage")
    step_types = [s["type"] for s in compiled.workflow_spec["steps"]]

    assert "tool.call" not in step_types, (
        "incident_triage must not include tool.call steps. The demo is "
        "explicitly safe-by-default; production mutations would defeat the "
        "wedge story."
    )
    assert "webhook.wait" not in step_types, (
        "incident_triage must not suspend on a webhook — the demo is "
        "expected to complete end-to-end without external input."
    )
    assert "artifact.store" in step_types, (
        "incident_triage must finish with artifact.store so the demo "
        "always produces an audit record."
    )


def test_incident_triage_classification_required_fields():
    """The classify_incident step's required fields are demo-critical —
    they define the operator-visible classification. Drift here would
    silently change what the demo presents."""
    compiled = _load_compiled("incident_triage")
    classify = next(s for s in compiled.workflow_spec["steps"] if s["id"] == "classify_incident")
    required = set(classify["expect"]["required"])
    expected = {
        "incident_type",
        "severity",
        "affected_systems",
        "probable_cause",
        "recommended_action",
        "escalation_required",
        "confidence",
        "operator_summary",
    }
    assert expected.issubset(required), (
        f"classify_incident.expect.required must include {expected}; "
        f"missing: {expected - required}"
    )


def test_incident_triage_pii_blocked():
    """Incident triage must default-deny PII so demo data doesn't leak to
    the LLM in plain text."""
    compiled = _load_compiled("incident_triage")
    assert compiled.policies["pii"]["allow"] is False


# -------------------------------------------------------------------------------------- #
# change_approval_ansible                                                                #
# -------------------------------------------------------------------------------------- #


def test_change_approval_uses_real_ansible_tool():
    """The change-approval wedge proves 'deterministic Ansible after
    approval'. Both Ansible steps must use the real `ansible_run` tool —
    not an HTTP shim that fakes Ansible."""
    compiled = _load_compiled("change_approval_ansible")
    ansible_steps = [
        s
        for s in compiled.workflow_spec["steps"]
        if s["type"] == "tool.call" and s.get("tool") == "ansible_run"
    ]
    assert len(ansible_steps) == 2, (
        f"Expected exactly two ansible_run steps (check + apply); got " f"{len(ansible_steps)}"
    )
    modes = sorted(s["params"]["mode"] for s in ansible_steps)
    assert modes == [
        "apply",
        "check",
    ], f"Expected one check and one apply Ansible step; got modes={modes}"


def test_change_approval_has_approval_gate_before_apply():
    """The human.approval step must sit BETWEEN the check and the apply.
    If apply ever runs before approval, the demo's central wedge claim
    fails."""
    compiled = _load_compiled("change_approval_ansible")
    steps = compiled.workflow_spec["steps"]

    def index_of(predicate):
        for i, s in enumerate(steps):
            if predicate(s):
                return i
        return -1

    check_idx = index_of(
        lambda s: s["type"] == "tool.call"
        and s.get("tool") == "ansible_run"
        and s["params"]["mode"] == "check"
    )
    approval_idx = index_of(lambda s: s["type"] == "human.approval")
    apply_idx = index_of(
        lambda s: s["type"] == "tool.call"
        and s.get("tool") == "ansible_run"
        and s["params"]["mode"] == "apply"
    )

    assert check_idx != -1, "Missing Ansible check step"
    assert approval_idx != -1, "Missing human.approval step"
    assert apply_idx != -1, "Missing Ansible apply step"
    assert check_idx < approval_idx < apply_idx, (
        f"Step order must be check ({check_idx}) → approval "
        f"({approval_idx}) → apply ({apply_idx}). Apply must NEVER run "
        f"before the approval gate."
    )


def test_change_approval_apply_inputs_match_check_inputs():
    """The applied change must be exactly what the approver reviewed. If
    the playbook or extra_vars between check and apply ever drift, the
    approval is meaningless."""
    compiled = _load_compiled("change_approval_ansible")
    ansible_steps = [
        s
        for s in compiled.workflow_spec["steps"]
        if s["type"] == "tool.call" and s.get("tool") == "ansible_run"
    ]
    check_step = next(s for s in ansible_steps if s["params"]["mode"] == "check")
    apply_step = next(s for s in ansible_steps if s["params"]["mode"] == "apply")

    # Compare every params key except 'mode'
    check_params = {k: v for k, v in check_step["params"].items() if k != "mode"}
    apply_params = {k: v for k, v in apply_step["params"].items() if k != "mode"}
    assert check_params == apply_params, (
        "Ansible check and apply must use the same playbook, inventory, "
        "limit, and extra_vars. Any drift means the approver did not "
        "actually authorize what was applied."
    )


def test_change_approval_bundled_ansible_files_exist():
    """The demo ships with a small playbook + inventory so it runs from a
    clean local setup. If either file disappears, the demo breaks."""
    playbook = ANSIBLE_DIR / "demo_change.yml"
    inventory = ANSIBLE_DIR / "demo_inventory.ini"
    assert playbook.exists(), (
        f"Bundled demo playbook missing at {playbook}. Add a tiny safe "
        f"playbook so the change-approval demo runs without external infra."
    )
    assert inventory.exists(), (
        f"Bundled demo inventory missing at {inventory}. Add a localhost "
        f"inventory so the demo runs without SSH."
    )
    # Playbook should be valid YAML
    playbook_data = yaml.safe_load(playbook.read_text())
    assert (
        isinstance(playbook_data, list) and playbook_data
    ), "demo_change.yml must parse to a non-empty list of plays"


def test_change_approval_demo_inventory_uses_python_auto_discovery():
    """Regression: the inventory must let Ansible auto-discover Python on the
    target host. A hard-coded path (e.g. /usr/bin/python3) or the
    /usr/bin/env\\ python3 trick breaks on macOS, where python3 typically
    lives under /opt/homebrew or /usr/local, not /usr/bin. The fix is to use
    ansible_python_interpreter=auto_silent (or auto)."""
    raw = (ANSIBLE_DIR / "demo_inventory.ini").read_text()
    # Strip INI comments (';' and '#') so explanatory prose doesn't trip the
    # assertions — we only care about the live host-vars line.
    active = "\n".join(
        line
        for line in raw.splitlines()
        if line.strip() and not line.lstrip().startswith((";", "#"))
    )
    # Must use auto-discovery so the demo runs portably.
    assert "ansible_python_interpreter=auto" in active, (
        "demo_inventory.ini must set ansible_python_interpreter=auto_silent "
        "(or auto). Hard-coded interpreter paths break on macOS."
    )
    # Must NOT use the broken /usr/bin/env\ python3 form that caused the
    # original 'module interpreter not found' failure on macOS.
    assert "/usr/bin/env" not in active, (
        "demo_inventory.ini must not point ansible_python_interpreter at a "
        "/usr/bin/env-style path: Ansible execs the value literally as a "
        "single binary and /usr/bin/env\\ python3 is not a real file."
    )


# -------------------------------------------------------------------------------------- #
# callback_driven_maintenance                                                            #
# -------------------------------------------------------------------------------------- #


def test_callback_maintenance_suspends_on_webhook_wait():
    """The callback wedge proves suspend/resume on an external callback.
    The workflow must include a webhook.wait step — without it there is
    no suspension to resume from."""
    compiled = _load_compiled("callback_driven_maintenance")
    wait_steps = [s for s in compiled.workflow_spec["steps"] if s["type"] == "webhook.wait"]
    assert len(wait_steps) == 1, f"Expected exactly one webhook.wait step; got {len(wait_steps)}"
    wait_step = wait_steps[0]
    assert wait_step["params"].get("event_name"), (
        "webhook.wait requires params.event_name (enforced by the compiler) "
        "— the demo must keep this set"
    )


def test_callback_maintenance_persists_records_around_suspension():
    """The audit story requires that BOTH the prep record (before suspension)
    AND the completion record (after resume) get stored. Without the prep
    record, a never-resumed run has no audit trail; without the completion
    record, the resume path has no closing artifact."""
    compiled = _load_compiled("callback_driven_maintenance")
    steps = compiled.workflow_spec["steps"]

    types = [s["type"] for s in steps]
    artifact_indexes = [i for i, t in enumerate(types) if t == "artifact.store"]
    wait_indexes = [i for i, t in enumerate(types) if t == "webhook.wait"]

    assert len(artifact_indexes) >= 2, (
        "Expected at least two artifact.store steps: prep (before suspend) "
        "and completion (after resume)"
    )
    assert wait_indexes, "Expected a webhook.wait step"
    wait_idx = wait_indexes[0]
    assert any(i < wait_idx for i in artifact_indexes), (
        "Expected at least one artifact.store BEFORE webhook.wait so a "
        "never-resumed run still has audit evidence"
    )
    assert any(i > wait_idx for i in artifact_indexes), (
        "Expected at least one artifact.store AFTER webhook.wait so the "
        "completed run captures the callback payload"
    )


def test_callback_maintenance_no_external_http_in_demo_path():
    """The demo must reach suspension without calling any external HTTP
    service. A demo that requires a live external system to suspend is
    not runnable on a clean local setup."""
    compiled = _load_compiled("callback_driven_maintenance")
    for step in compiled.workflow_spec["steps"]:
        if step["type"] == "tool.call":
            tool_name = step.get("tool", "")
            assert tool_name != "http_request", (
                f"callback_driven_maintenance step {step['id']} uses "
                f"http_request — the demo must not depend on an external "
                f"orchestrator to suspend or resume"
            )
