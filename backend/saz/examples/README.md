# Saz Demos

Three "wedge" demos showcase Saz's market position: **AI assists, policy
constrains, humans approve, deterministic tools execute, and every action is
auditable.** Each demo is a YAML workflow under
`backend/saz/examples/unified/` and is loaded automatically by the
`TemplateManager` on backend start.

| Demo | File | What it proves |
|---|---|---|
| Incident Triage | `incident_triage.yaml` | AI classification + safe audit artifact, no production mutations |
| Change Approval with Ansible | `change_approval_ansible.yaml` | AI risk summary → Ansible check → human approval → Ansible apply |
| Callback-Driven Maintenance | `callback_driven_maintenance.yaml` | Suspend on `webhook.wait`, resume via external callback POST |

All three are marked `recommended: true` and carry the `wedge-demo` tag. They
can be browsed via:

```bash
curl -s http://localhost:8000/api/templates/ | jq '.[] | select(.tags | contains(["wedge-demo"]))'
```

This guide describes how to run each one from a clean local setup, what to
inspect in the UI, and the known limitations.

---

## Prerequisites

- Backend running on `http://localhost:8000` (see top-level `README.md`).
- Frontend running on `http://localhost:3000`.
- An LLM provider configured for `LiteLLM` (set `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, or any other LiteLLM-supported credential in your
  backend `.env`). The demos call `ai.extract` and `ai.generate`; without
  a provider configured, those steps will fail with a clear error.
- For the Ansible demo only: install `ansible-runner` (`pip install
  ansible-runner`) and have the `ansible-playbook` binary on PATH. Honest
  mode: if either is missing, the `ansible_run` step fails with an
  actionable error — the demo does not silently fake success.

> Saz is a self-hosted prototype. None of the demos require an external
> SaaS account. All three are safe to run locally.

---

## Loading a demo into a flow

Templates are read-only. To run a demo you register it as a flow and then
submit form data to trigger a run.

**From the UI (recommended):**
1. Open `http://localhost:3000/flows/new`.
2. Click **Browse templates** in the header.
3. The picker lists the wedge demos first with a highlighted badge.
   Search by tag (e.g. `ansible`) to narrow.
4. Click a row — the YAML loads into the editor.
5. Click **Save** to register the flow.

**From the CLI:**

```bash
# 1. Fetch the demo YAML from the templates API
curl -s http://localhost:8000/api/templates/incident_triage \
  | jq -r .yaml > /tmp/incident_triage.yaml

# 2. Register as a flow
curl -s -X POST http://localhost:8000/api/v1/flows \
  -H "Content-Type: application/x-yaml" \
  --data-binary @/tmp/incident_triage.yaml
```

---

## Demo 1 — Incident Triage (`incident_triage.yaml`)

**Product story.** An alert arrives. AI classifies the incident (type,
severity, affected systems, probable cause, recommended action,
escalation flag, confidence), writes a ChatOps-ready summary, and the run
persists a complete audit artifact. AI never mutates production — the
recommended action is recorded as a **proposal** for the on-call team.

**Run lifecycle.** `queued → running → completed`. No suspension. No
deterministic tool calls beyond `artifact.store`.

**How to run.**

1. Register the flow (see "Loading a demo into a flow" above).
2. Submit a form payload — example:

   ```bash
   curl -s -X POST http://localhost:8000/api/v1/runs \
     -H "Content-Type: application/json" \
     -d '{
       "flow_name": "incident_triage",
       "payload": {
         "alert_title": "P1 — checkout 5xx spike",
         "alert_description": "5xx error rate on checkout-api jumped from 0.1% to 8% over the last 10 minutes. Affected region: us-east-1. Some customers seeing failed payments.",
         "affected_service": "checkout-api",
         "environment": "prod",
         "source_system": "datadog",
         "severity_hint": "high",
         "customer_impact": "Payments failing for ~5% of traffic",
         "on_call_team": "payments-on-call"
       }
     }'
   ```

3. Open `http://localhost:3000/runs/<run_id>` and watch the three steps run.

**What to look at in the UI.**

- **Step `classify_incident`** — expand `output` to see the strict JSON
  classification. `escalation_required` should be `true` for prod with
  customer impact.
- **Step `write_chatops_summary`** — expand `output` to read the short
  paste-into-Slack summary.
- **Step `store_triage_record`** — `output.artifact_id` is the UUID of the
  stored audit artifact. The artifact contains the full alert, the
  classification, the ChatOps summary, and the proposed next action.
- **Event timeline (console panel)** — `step.started` / `step.completed`
  events confirm the order. Every AI op emits token + cost events
  attributable to this run.

**Known limitations.**

- The "next action" is a proposal, not an execution. The demo intentionally
  does not call PagerDuty or any production system.
- AI output quality depends on the model. The strict `expect` schema
  guarantees the output **shape**; the model still controls the content.

---

## Demo 2 — Change Approval with Ansible (`change_approval_ansible.yaml`)

**Product story.** A change request is intaken. AI produces a structured
risk summary (blast radius, pre-checks, rollback summary, recommendation).
Ansible runs in `--check` mode against a bundled safe playbook. A human
approval gate pauses the run. On approval, Ansible runs in apply mode
against the same playbook with the same inputs. Every step is audited.

**Bundled playbook + inventory.**

- `backend/saz/examples/ansible/demo_change.yml` — idempotent localhost
  playbook that touches `/tmp/saz-demo/last_change.txt`. No real
  infrastructure is changed.
- `backend/saz/examples/ansible/demo_inventory.ini` — single localhost host
  using `ansible_connection=local`.

**Required environment variables.**

```bash
# Point the demo at the bundled playbook + inventory
export SAZ_DEMO_ANSIBLE_PLAYBOOK="$(pwd)/backend/saz/examples/ansible/demo_change.yml"
export SAZ_DEMO_ANSIBLE_INVENTORY="$(pwd)/backend/saz/examples/ansible/demo_inventory.ini"

# Optional: explicitly allowlist the bundled playbook root for the Ansible tool
# (the tool defaults to "no allowlist = allow all"; only set this in production)
# export SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS="$(pwd)/backend/saz/examples/ansible"
```

Set these in the backend process environment before starting `uvicorn`.

**Run lifecycle.** `queued → running → suspended (at request_approval) →
queued → running → completed`.

**How to run.**

1. Register the flow.
2. Submit a form payload — example:

   ```bash
   curl -s -X POST http://localhost:8000/api/v1/runs \
     -H "Content-Type: application/json" \
     -d '{
       "flow_name": "change_approval_ansible",
       "payload": {
         "change_title": "Touch demo marker file",
         "target_environment": "dev",
         "target_hosts": "localhost",
         "requested_action": "Render /tmp/saz-demo/last_change.txt to mark a safe demo change",
         "maintenance_window": "2026-05-20 02:00–04:00 UTC",
         "rollback_plan": "Delete /tmp/saz-demo/last_change.txt",
         "risk_hint": "low",
         "requester": "operator@example.com"
       }
     }'
   ```

3. Open `http://localhost:3000/runs/<run_id>`.

**Expected UI lifecycle.**

1. **summarize_change** — AI risk summary visible in step output.
2. **ansible_check** — `mode: check`, `changed: false` (dry-run never
   commits). Recap shows ok=1, changed=0.
3. **store_dryrun_artifact** — audit artifact with the dry-run recap.
4. **request_approval** — run becomes **suspended**. The
   `HumanApprovalPanel` appears at the top of the run page.
5. Click **Approve and Continue**. The run resumes.
6. **ansible_apply** — `mode: apply`. `changed: true` on first run.
7. **store_change_record** — final audit artifact containing the AI
   summary, dry-run recap, approval payload, and apply recap.

**Triggering approval/rejection from the UI.** The `HumanApprovalPanel`
shows tabs with the AI summary, the previous step outputs (including the
dry-run recap), and the remaining steps. Use **Approve** or **Reject**.
Approval calls `POST /api/v1/runs/{id}/resume` with
`{resume_data: {approved: true, ...}}`.

**Triggering approval via webhook callback (CLI).** The executor also
stores a `callback_id` in `run.error` for the suspended approval step.
External systems can call:

```bash
RUN_ID=...      # from the run detail page
CALLBACK_ID=$(curl -s http://localhost:8000/api/v1/runs/$RUN_ID | jq -r .error.callback_id)
curl -s -X POST http://localhost:8000/api/v1/webhooks/callback/$CALLBACK_ID \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'
```

Reject by sending `{"action": "reject", "reason": "Window expired"}`.

**Known limitations.**

- The bundled playbook is intentionally safe. It does not demonstrate any
  real production change. Operators should swap in their own playbook by
  re-pointing `SAZ_DEMO_ANSIBLE_PLAYBOOK` / `SAZ_DEMO_ANSIBLE_INVENTORY`.
- `ansible-runner` and the `ansible-playbook` binary must be installed.
  Without them, both `ansible_run` steps fail with a Python import error.
  This is by design — Saz does not fake Ansible success.
- The Ansible tool's policy allowlist (`allowed_playbook_roots`,
  `allowed_inventories`) is empty by default — which means **all** paths
  are allowed. In production, set these to your trusted playbook roots.

---

## Demo 3 — Callback-Driven Maintenance (`callback_driven_maintenance.yaml`)

**Product story.** A maintenance request is intaken. AI validates the
plan and lists preconditions. The run stores a prep audit record and then
suspends on a `webhook.wait` step. An external system (or the operator)
POSTs to the generated callback URL to resume the run. On approve, the
run finalizes the audit record. On reject, the run fails with the reason
recorded.

**Run lifecycle.** `queued → running → suspended → queued → running →
completed` (approve path), or `queued → running → suspended → failed`
(reject path).

**How to run.**

1. Register the flow.
2. Submit a form payload:

   ```bash
   curl -s -X POST http://localhost:8000/api/v1/runs \
     -H "Content-Type: application/json" \
     -d '{
       "flow_name": "callback_driven_maintenance",
       "payload": {
         "maintenance_title": "Edge cache rebuild",
         "target_system": "edge-cache",
         "environment": "staging",
         "maintenance_window": "2026-05-20 02:00–04:00 UTC",
         "external_ticket_id": "CHG-2024-001",
         "notification_channel": "#sre-on-call",
         "expected_callback_source": "deploy-bot"
       }
     }'
   ```

3. Open `http://localhost:3000/runs/<run_id>`.

**Expected UI lifecycle.**

1. **validate_maintenance_plan** — AI plan validation visible.
2. **store_prep_record** — prep artifact stored.
3. **wait_for_completion_callback** — run becomes **suspended**.
4. The Run page renders a **Callback panel** showing the full callback URL,
   the callback_id, and "Send approve callback" / "Send reject callback"
   buttons. (See `frontend/components/runs/webhook-callback-panel.tsx`.)
5. Click **Send approve callback** with a payload like
   `{"applied_changes": ["cache flushed", "warm cache rebuilt"]}`.
6. The run resumes. **store_completion_record** writes the final artifact,
   which includes the callback payload at
   `callback.callback_id` + `callback.action` + the operator-supplied data.

**Triggering the callback from CLI.** The callback_id is also surfaced on
the run detail JSON:

```bash
RUN_ID=...
CALLBACK_ID=$(curl -s http://localhost:8000/api/v1/runs/$RUN_ID | jq -r .error.callback_id)

# Approve
curl -s -X POST http://localhost:8000/api/v1/webhooks/callback/$CALLBACK_ID \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","data":{"applied_changes":["cache flushed"]}}'

# Reject
curl -s -X POST http://localhost:8000/api/v1/webhooks/callback/$CALLBACK_ID \
  -H "Content-Type: application/json" \
  -d '{"action":"reject","reason":"Window expired"}'
```

**Negative paths to demo.**

- **Unknown callback_id** → 404, run keeps its suspended state.
- **Duplicate callback** → second POST returns
  `{"status":"already_processed", ...}`; the run does not double-execute.
- **Reject** → run transitions `suspended → failed`. The rejection reason
  is preserved in `run.error.message` for the audit trail.

**Known limitations.**

- The callback URL must be reachable from whatever external system is
  expected to send the callback. For local demos, both the run and the
  caller are on `localhost`.

---

## Suspension timeouts

Both `human.approval` and `webhook.wait` suspensions are bounded by a
deadline. The executor reads `timeout_minutes` (or `timeout_seconds`) from
the step's `params`; if neither is set the run is bounded by a 24h
default so suspended runs cannot accumulate forever.

The deadline is stored on `run.error.timeout_at` (ISO-8601 UTC) at
suspension time. A background `SuspensionSweeper` runs every
`SUSPENSION_SWEEP_INTERVAL_SECONDS` (default 60s) and transitions any
suspended run whose `timeout_at` has passed to `failed` with type
`SuspensionTimeout`. The audit trail records `run.failed` (and
`approval.denied` for human approvals) so the run-detail page reflects
the timeout on the next refetch.

A late callback to a timed-out run does **not** 404 — the
`callback_id` is preserved in the failed-run error payload, so the
`/api/v1/webhooks/callback/{id}` endpoint responds with
`{"status":"already_processed"}` and an external caller can detect that
its message was dropped.

Tuning:

| Setting | Default | What it does |
|---|---|---|
| `SUSPENSION_SWEEP_INTERVAL_SECONDS` | 60 | Sweep frequency |
| `SUSPENSION_SWEEP_BATCH_LIMIT` | 100 | Max runs reaped per sweep |
| `SUSPENSION_SWEEP_ENABLED` | true | Toggle the sweeper off (used by tests) |

---

## Audit and observability

Every demo emits these event types (visible in the run detail console
panel and in the WebSocket stream `/api/v1/runs/{id}/events`):

- `run.started`, `run.completed`, `run.failed`, `run.suspended`, `run.resumed`
- `step.started`, `step.completed`, `step.failed`, `step.suspended`
- `tool.started`, `tool.completed` — including AI op invocations
- `approval.requested`, `approval.granted`, `approval.denied`
- `webhook.callback_received`
- `policy.checked` (PII, budget, rate limit)

These events are persisted and form the audit trail that the demos are
built around.

---

## Testing

```bash
# All demos must compile and load via the TemplateManager
cd backend
python -m pytest -n auto tests/examples/test_unified_templates.py

# Wedge-specific tests
python -m pytest -n auto tests/examples/test_wedge_demos.py
```