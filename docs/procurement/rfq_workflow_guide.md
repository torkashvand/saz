# RFQ/RFP Drafting Workflow — Usage & Testing Guide

This workflow turns structured intake from the project and procurement teams into a
formatted GÉANT RFQ Word document, with compliance gates, procurement review, optional
market consultation, and dual sign-off.

- **Workflow:** `backend/saz/examples/unified/rfq_rfp_drafting.yaml`
- **Render tool:** `docx_render` (`backend/saz/tools/docx_tool.py`)
- **Template:** `backend/saz/examples/templates/rfq_template.docx` (tokenized copy of the
  GÉANT "RFQ HRIS System" template)
- **Placeholder map:** [`rfq_placeholder_map.md`](./rfq_placeholder_map.md)
- **Example outputs:** [`examples/`](./examples/) (`rfq_draft_T88815.docx`, `rfq_final_T88815.docx`)

The process mirrors the GÉANT RFP workflow diagram: discuss scope/objectives → assemble
procurement + project input → draft → procurement review → (optional) market consultation
→ dual sign-off → finalized RFQ.

---

## Lifecycle

```
form (project + procurement intake)
  → ai.extract     validate_inputs       structure inputs, flag missing/inconsistent (incl. weight sums)
  → condition      gate_budget           deterministic money gate (caps + value)
  → ai.evaluate    pont_check            PONT compliance (pass + issues[])          [when gate passed]
  → ai.generate    draft_narrative       background / objective / scope             [when gate passed]
  → human.approval procurement_review    officer reviews narrative + PONT findings  [when gate passed]
  → tool.call      render_draft          DRAFT .docx (require_all=false)            [when gate passed]
  → condition      needs_consultation    branch if consultation_required            [when gate passed]
       → webhook.wait supplier_feedback  suspend for supplier feedback (callback)   [when gate passed & consultation]
  → ai.generate    finalize_narrative    fold feedback if any; else pass through    [when gate passed]
  → human.approval procurement_signoff   final procurement approval                 [when gate passed]
  → human.approval project_signoff       final project-team approval                [when gate passed]
  → tool.call      render_final          FINAL .docx from finalize_narrative        [when gate passed]
  → artifact.store audit_record          full audit trail                           [when gate passed]
```

Every step after `gate_budget` carries a `when: "{{ $step('gate_budget').result == true }}"`
guard. A Saz `condition` does not halt the run by itself — the guard is what makes
the gate actually block. If the gate fails, all downstream steps are **skipped** (no
drafting, no approval, no render) and the run completes with those steps marked
`skipped` in the timeline. `finalize_narrative` always runs when the gate passes: it
folds supplier feedback into the narrative when market consultation occurred, and
otherwise returns the draft unchanged — it is the single source the FINAL document
renders from.

---

## Intake form

The run collects one form at start, with two sections (a Saz run cannot present two
separate form steps, so both teams' fields are gathered together).

**Project team:** `project_name`, `objective_input`, `scope_input`, `background_input`,
`technical_requirements`, `criticality` (low/medium/high), `num_users`,
`data_sensitivity` (none/internal/confidential/highly_confidential), `estimated_value_eur`,
`contract_duration`, `vendor_constraints`.

**Procurement team:** `pricing_model`, `budget_cap_licenses_eur`,
`budget_cap_implementation_eur`, `sourcing_strategy`, `gdpr_data_residency`,
`security_requirements`, `minimum_requirements` (one per line), `weight_qualitative_pct`,
`weight_price_pct`, `q1_pct`, `q2_pct`, `q3_pct`, `reference_number`, `date_of_issue`,
`deadline_clarification`, `deadline_response`, `eval1_end`, `eval2_end`, `awarding_date`,
`commencement_date`, `contact_name`, `contact_role`, `contact_phone`, `contact_email`,
`consultation_required` (boolean).

Each form field maps to one or more template tokens — see the
[placeholder map](./rfq_placeholder_map.md).

---

## Running it

1. **Register the workflow:**
   ```bash
   curl -s -X POST localhost:8000/api/v1/flows \
     -H 'Content-Type: application/json' \
     --data @- <<'JSON'
   { "yaml": "<contents of rfq_rfp_drafting.yaml>" }
   JSON
   ```
   (Or use the Saz UI / template manager, which auto-discovers files under
   `saz/examples/unified/`.)

2. **Start a run** with a form payload. Example payload (the HRIS test case):
   ```json
   {
     "project_name": "HR Information System",
     "objective_input": "Find a cost-effective, modern, well-supported HR system.",
     "scope_input": "A core HR system with optional modules for future expansion.",
     "background_input": "GÉANT seeks to replace its existing HR Information System.",
     "technical_requirements": "SSO (OIDC/SAML2); EU/UK data residency; TLS 1.2+; O365/Entra integration.",
     "criticality": "high",
     "num_users": 180,
     "data_sensitivity": "confidential",
     "estimated_value_eur": 30000,
     "contract_duration": "2 years + 3x1 year extensions",
     "pricing_model": "per_user",
     "budget_cap_licenses_eur": 20000,
     "budget_cap_implementation_eur": 10000,
     "sourcing_strategy": "Open EU competition",
     "gdpr_data_residency": "Data stored within EU or UK",
     "security_requirements": "Encryption in transit and at rest; activity logging.",
     "minimum_requirements": "1. SSO via OIDC/SAML2\n2. EU/UK data residency\n3. TLS 1.2+",
     "weight_qualitative_pct": 80,
     "weight_price_pct": 20,
     "q1_pct": 50,
     "q2_pct": 20,
     "q3_pct": 10,
     "reference_number": "T88815",
     "date_of_issue": "05/07/2024",
     "deadline_clarification": "15/07/2024",
     "deadline_response": "19/07/2024",
     "eval1_end": "02/08/2024",
     "eval2_end": "09/08/2024",
     "awarding_date": "15/08/2024",
     "commencement_date": "01/10/2024",
     "contact_name": "Badreddine Ajbar El Gueriri",
     "contact_role": "Buyer",
     "contact_phone": "+31 6 29003633",
     "contact_email": "badre.ajbar@geant.org",
     "consultation_required": false
   }
   ```
   Note `q1_pct + q2_pct + q3_pct` must equal 100 and `weight_qualitative_pct +
   weight_price_pct` must equal 100, or `gate_budget` blocks the run.

3. **Approvals.** The run suspends at `procurement_review`; the named approver
   approves/rejects via the approvals API (or UI). It suspends again at
   `procurement_signoff` and `project_signoff`.

4. **Market consultation (optional).** If `consultation_required` is true, the run
   suspends at `supplier_feedback` (a `webhook.wait`). A supplier/coordinator resumes it:
   ```bash
   curl -s -X POST localhost:8000/api/v1/webhooks/callback/<callback_id> \
     -H 'Content-Type: application/json' \
     -d '{"action": "approve", "data": {"feedback": "Consider adding SCIM provisioning."}}'
   ```
   Send `{"action": "reject", "reason": "..."}` to fail the consultation.

5. **Output.** `render_final` produces the final `.docx` as an artifact; `audit_record`
   stores the full trail (inputs, validation, PONT result, both approvals, document
   artifact ids).

The template path is overridable via the `SAZ_RFQ_TEMPLATE` environment variable
(default: `saz/examples/templates/rfq_template.docx`).

---

## Compliance gates

- **`gate_budget`** (deterministic): passes only when license budget ≤ €20,000,
  implementation budget ≤ €10,000, and estimated value < €100,000. When it fails, every
  downstream step is skipped via its `when` guard, so no draft or document is produced.
  (The condition grammar has no arithmetic operator, so the gate uses comparisons only.)
- **Weight-sum (transparency)**: `validate_inputs` flags `qualitative + price` ≠ 100 and
  `Q1 + Q2 + Q3` ≠ 100 in its `inconsistencies`, which surface in the procurement review
  for the officer to act on.
- **`pont_check`** (`ai.evaluate`): assesses the procurement inputs against PONT
  (Proportional, Objective, Non-discriminatory, Transparent) and returns `pass` plus a
  list of `issues`, surfaced in the procurement review payload (advisory — the officer
  gates on it at `procurement_review`).

---

## Rebuilding the template

The tokenized template is derived once from the original GÉANT `.docx`. Re-run the build
script if the source template or the token hints change:

```bash
cd backend
uv run python -m saz.examples.templates.build_rfq_template \
  --source "/path/to/(EXAMPLE) RFQ HRIS System.docx"
```

This regenerates `rfq_template.docx` and `docs/procurement/rfq_placeholder_map.md`. Only
spans matching a hint in `saz/examples/templates/rfq_tokens.py` become `{{tokens}}`; all
other highlighted text is left as the original example content.

---

## Generating the example outputs

```bash
cd backend
uv run python ../scripts/generate_rfq_example.py
```

Writes `rfq_draft_T88815.docx` and `rfq_final_T88815.docx` to `docs/procurement/examples/`
using the HRIS test data (no LLM required — narrative values are canned).

---

## Testing

```bash
cd backend
uv run pytest \
  tests/unit/test_rfq_tokens.py \
  tests/unit/test_build_rfq_template.py \
  tests/unit/test_docx_tool.py \
  tests/examples/test_rfq_rfp_workflow.py \
  tests/integration/test_rfq_render_end_to_end.py -q
```

The example workflow is also exercised by the repo's auto-discovery suites
(`tests/acceptance/test_examples_execute_safely.py`,
`tests/integration/test_examples_plan_and_ground.py`).

---

## Known limitations (POC)

- **Output is `.docx` only** (no PDF conversion).
- **22 of 26 fields are template placeholders.** Four canonical fields cannot be
  tokenized from the original and remain fixed example text — see the Notes column in the
  [placeholder map](./rfq_placeholder_map.md): title, Background section, contact email
  (a hyperlink), and the implementation budget cap (shares one highlighted span with the
  licenses cap).
- **Single combined form** rather than two sequential team handoffs.
- **`minimum_requirements`** replaces the first requirement span; the original example's
  remaining requirement rows stay as fixed text.
- **Rendered `.docx` is not a separate queryable artifact row.** The file is written to
  the artifact storage directory and its `artifact_id`/path are recorded in the
  `audit_record` (an `artifact.store` row), but the executor only persists first-class
  `Artifact` rows for `artifact.store` steps, not for `docx_render`.
- **A blocked run completes with skipped steps** (it does not fail). When `gate_budget`
  fails, the downstream steps are marked `skipped`; the run status is `completed`.
- **Weight-sum is validated by AI + human review**, not the deterministic gate (the
  condition grammar has no arithmetic).
- **RAG / retrieval-augmented Q&A is out of scope** (planned for a later phase).
