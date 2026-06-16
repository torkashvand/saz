# RFQ/RFP Drafting Workflow — Design Spec

**Date:** 2026-06-16
**Status:** Approved (design); pending implementation plan
**Scope:** Proof-of-concept for GÉANT procurement: automate RFQ/RFP draft generation
from a standardized Word template using the Saz workflow framework.
**Out of scope:** RAG / retrieval-augmented Q&A and thesis-specific RAG (deferred to Phase 2).

---

## 1. Goal

Streamline GÉANT's tender process by:

1. Gathering structured intake from the project and procurement teams.
2. Validating inputs against mandatory-field, budget, and PONT
   (Proportional, Objective, Non-discriminatory, Transparent) rules.
3. Drafting formal narrative sections from user inputs (no invented content).
4. Merging fixed template text with user data into a real `.docx` that matches
   the original GÉANT RFQ format.
5. Routing through procurement review, optional market consultation, and dual
   final sign-off, with a full audit trail.

The reference inputs are the GÉANT artifacts in `~/Documents/saz/`:
`(EXAMPLE) RFQ HRIS System.docx` (template), `RFP Workflow.png` (process diagram),
`Procurment.pdf` (procurement principles).

---

## 2. Constraints discovered in the Saz codebase

These shaped the design; each is a deliberate adaptation of the original brief to
what the Saz compiler/runtime actually supports.

| Brief assumption | Reality in Saz | Resolution |
|---|---|---|
| `tool.call` produces a Word/PDF doc | No native doc renderer; tools are `http_request`, `ansible_run`, `artifact.store/retrieve` | Add **one** new tool, `docx_render`, registered in the tool registry. |
| `human.multi_approval` step | No such step type; only `human.approval` and `webhook.wait` | Market consultation = `condition` → `webhook.wait`; dual sign-off = two sequential `human.approval` steps. |
| Two `input.form` steps | A run collects exactly **one** top-level `form` at start; no `input.form` step type | One combined form with Project and Procurement sections. |

Allowed step types (compiler): `ai.*`, `tool.call`, `condition`, `human.approval`,
`webhook.wait`, `artifact.store`, `artifact.retrieve`.

---

## 3. Architecture

A single **deterministic** workflow drives the full lifecycle. The only new code is
the `docx_render` tool. The real Word template is preserved exactly: a one-time prep
step derives a *tokenized* copy (yellow-highlighted variable spans replaced with
`{{token}}` markers), and the tool fills tokens at runtime, leaving original styles,
headers, footer, and logo untouched.

```
(EXAMPLE) RFQ HRIS System.docx
        │  build_rfq_template.py  (one-time: merge fragmented highlighted runs,
        │                          replace each highlighted span with {{token}})
        ▼
rfq_template.docx  +  placeholder_map (token → meaning → form field)
        │
Saz run:
  form (project + procurement)
   → ai.extract   validate_inputs   (structure, classify, flag missing)
   → condition    gate_budget       (caps + required fields + weight-sum)
   → ai.evaluate  pont_check        (PONT pass + issues[])
   → ai.generate  draft_narrative   (background/objective/scope, provided data only)
   → human.approval procurement_review
   → docx_render  render_draft      → DRAFT .docx artifact
   → condition    needs_consultation
        → webhook.wait supplier_feedback (timeout)   [only if required]
   → ai.generate  incorporate_feedback                [when: consultation]
   → human.approval procurement_signoff
   → human.approval project_signoff
   → docx_render  render_final       → FINAL .docx artifact
   → artifact.store audit_record
```

---

## 4. Components

| Component | Location | Purpose |
|---|---|---|
| `docx_render` tool | `backend/saz/tools/docx_tool.py`; registered in `backend/saz/tools/registry.py` (`create_default_registry`) | Token substitution into a `.docx`, preserving formatting. Stores result via the artifact store; returns `artifact_id`, `path`, `filled` count, and `unfilled` token list. Depends on `python-docx`. |
| Tokenized template | `backend/saz/examples/templates/rfq_template.docx` | GÉANT template with yellow spans → `{{token}}`. |
| Template build script | `backend/saz/examples/templates/build_rfq_template.py` | Repeatable prep: reads the original docx, merges fragmented highlighted runs within each highlighted span, replaces each span with a named token, emits the placeholder map. |
| Workflow YAML | `backend/saz/examples/unified/rfq_rfp_drafting.yaml` | The full workflow; auto-discovered by example tests. |
| Placeholder mapping | `docs/procurement/rfq_placeholder_map.md` | token ↔ form field ↔ template section. |
| Usage / testing guide | `docs/procurement/rfq_workflow_guide.md` | How project & procurement teams run and test the workflow. |
| Example outputs | `docs/procurement/examples/` | Draft + final `.docx` generated from HRIS test data. |
| Tests | `backend/tests/unit/test_docx_tool.py`; example coverage under `backend/tests/examples/` and `backend/tests/integration/` | Tool behavior + workflow compile/ground/gates. |

### 4.1 `docx_render` tool contract

- **Spec name:** `docx_render`.
- **Inputs (`inputSchema`):**
  - `template` (string, required) — path to the tokenized `.docx`.
  - `values` (object, required) — map of token name → string value.
  - `output_name` (string, required) — artifact name for the rendered doc.
  - `require_all` (boolean, optional, default `true`) — if true, any unfilled
    `{{token}}` remaining in the document causes a structured failure.
- **Returns:** `{ artifact_id, path, filled, unfilled: [token, ...], byte_size }`.
- **Behavior:** async `execute(**kwargs)` returning `dict`; raises a structured
  error on missing template or (when `require_all`) unfilled mandatory tokens.
  Run/step context injected by the registry where needed; result redacted and
  persisted by the executor; downstream steps read `{{ $step('id').field }}`.

---

## 5. Workflow steps (detail)

1. **`form`** — combined intake. Project section: `project_name`, `objective`,
   `scope`, `technical_requirements`, `criticality` (enum), `num_users` (integer),
   `data_sensitivity` (enum), `estimated_value_eur` (number), `contract_duration`,
   `timeline`, `vendor_constraints`. Procurement section: `pricing_model` (enum),
   `budget_cap_licenses_eur` (number), `budget_cap_implementation_eur` (number),
   `sourcing_strategy`, `gdpr_data_residency`, `security_requirements`,
   `minimum_requirements` (text, one per line), `award_criteria` + weights
   (`weight_qualitative_pct`, `weight_price_pct`, `q1_pct`, `q2_pct`, `q3_pct`),
   `contact_name`, `contact_role`, `contact_phone`, `contact_email` (email),
   `reference_number`, `consultation_required` (boolean).
2. **`ai.extract` `validate_inputs`** — normalize/structure inputs; classify each
   requirement as high-level vs detailed; return `missing_fields[]`,
   `inconsistencies[]`. Strict `expect` (object, `required`, `additionalProperties:false`).
3. **`condition` `gate_budget`** — true only when mandatory fields present, budget
   caps respected (e.g. ≤ template's €20k licenses / €10k implementation, and the
   brief's < €100k threshold), and weights sum to 100. Blocks drafting otherwise.
4. **`ai.evaluate` `pont_check`** — assess procurement inputs against PONT; return
   `pass` (boolean) + `issues[]`. Surfaced into the procurement approval payload.
5. **`ai.generate` `draft_narrative`** — produce formal background, objective, and
   scope prose from provided inputs only; instruction forbids inventing content.
6. **`human.approval` `procurement_review`** — procurement officer reviews narrative
   and PONT findings before any document is produced.
7. **`docx_render` `render_draft`** — fill the tokenized template → DRAFT `.docx`.
8. **`condition` `needs_consultation`** + **`webhook.wait` `supplier_feedback`** —
   if `consultation_required`, suspend for supplier feedback callback (with timeout);
   otherwise skipped via `when`.
9. **`ai.generate` `incorporate_feedback`** — fold supplier feedback into the draft;
   guarded by `when: consultation_required`.
10. **`human.approval` `procurement_signoff`** then **`human.approval` `project_signoff`**
    — dual final sign-off.
11. **`docx_render` `render_final`** — produce the FINAL `.docx`.
12. **`artifact.store` `audit_record`** — inputs, validation result, PONT result,
    both approvals (who/when), supplier feedback, evaluation table, both document
    artifact ids, and version metadata.

---

## 6. Placeholder mapping (template → fields)

The tokenized template covers every yellow section found in the original:

- **Cover/meta:** system/RFQ title, date of issue, version, reference number.
- **Contact person:** name, role, phone, email.
- **Narrative:** background, objective of procurement, scope.
- **Procurement plan dates:** RFQ issued, clarification deadline, response deadline,
  end of evaluation phase 1, end of phase 2, awarding finalized, commencement date.
- **Minimum requirements:** numbered list rendered into the requirements block.
- **Evaluation criteria:** qualitative weight (e.g. 80%), Q1/Q2/Q3 sub-weights,
  price weight (e.g. 20%), budget caps (€ licenses / € implementation).
- **Evaluation phase descriptions** where variable.

The exhaustive token ↔ field ↔ section table lives in `rfq_placeholder_map.md`,
emitted by `build_rfq_template.py` and reconciled by hand to semantic field names.

---

## 7. PONT compliance & evaluation table

- `ai.evaluate` enforces PONT on procurement inputs and returns `issues[]`, shown in
  the procurement approval payload.
- The evaluation table (criteria + weights) is assembled from form inputs and rendered
  into the doc. Weight-sum-to-100 validation happens in `gate_budget`, so invalid /
  non-transparent scoring schemes are caught before drafting.

---

## 8. Error handling & safety

- Missing mandatory fields → flagged by `ai.extract`, blocked by `gate_budget`
  (no draft produced).
- `docx_render` reports `unfilled` tokens; with `require_all`, an unfilled mandatory
  token fails the step with a structured error — never emit a half-filled RFQ.
- No external side effects before procurement approval; `webhook.wait` handles
  late/duplicate callbacks per existing Saz semantics.
- Audit artifact records approver identity and reason at each gate; PII policy
  exceptions limited to audit-trail identity fields, following
  `change_approval_ansible.yaml`.

---

## 9. Testing strategy

- **Tool unit tests** (`test_docx_tool.py`): fills tokens; preserves formatting;
  reports unfilled tokens; `require_all` failure path; missing-template error;
  artifact stored.
- **Example tests** (auto-discovered from `saz/examples/unified/`): compiles with
  **zero** template warnings; first step grounds against a form payload; AI steps
  carry strict `expect` schemas with `required`.
- **Gate tests**: `gate_budget` blocks on over-cap budget, missing fields, and
  weight-sum ≠ 100; `pont_check` failure path surfaces issues; assert forbidden side
  effects (no render, no audit-complete) when blocked.
- **Worked example**: run with HRIS test data → DRAFT and FINAL `.docx`; verify
  structure matches the original template (sections present, tokens all filled).

---

## 10. Known POC limitations

- Minimum-requirements list and evaluation criteria render as formatted text / fixed
  rows, not dynamically grown table rows.
- Procurement input is entered alongside project input in a single form (one run),
  rather than as two sequential team handoffs.
- Output is `.docx` (the brief's "Word/PDF" — PDF conversion is not included).
- `python-docx` is added as a backend dependency for the new tool.

---

## 11. Deliverables

1. Saz YAML workflow (`rfq_rfp_drafting.yaml`).
2. `docx_render` tool + registration.
3. Tokenized template + build script.
4. Placeholder mapping doc.
5. Usage & testing documentation.
6. Example DRAFT and FINAL outputs from HRIS test data.
7. Tests (tool unit + workflow/gate coverage).
