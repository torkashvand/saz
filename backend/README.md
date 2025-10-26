# Saz - Agentic Forms & Workflows Platform

**Cost-efficient agentic workflow engine with deterministic execution.**
Define flows in YAML → render typed forms → run workflows with tools (HTTP, Ansible, webhooks, artifacts) under guardrails (budgets, PII, rate limits).

**Key Features:**
- **Deterministic by default**: Rule-based planner ($0 LLM cost for HTTP, Ansible, webhooks, conditions)
- **13 AI operations**: First-class `ai.*` nodes (extract, route, generate, plan, score, etc.) with strict contracts
- **Cost discipline**: ~$0.001-0.003 per AI call; total workflow typically < $0.01 for 5-7 AI steps
- **Compliance API**: Track tokens, cost, temperature, model per step; aggregate budgets
- **Expression engine**: Template resolver for `{{ $form.* }}`, `{{ $step('id').* }}`, `{{ $secret('name') }}`
- **First-class Ansible**: check/apply modes, credential injection, allowlist policies
- **Encrypted credentials vault**: Fernet-encrypted secrets, never logged
- **Triggers**: Manual, cron schedule, webhook
- **Execution history**: Full step I/O, replay from step N
- **Policy engine**: Token/cost budgets, PII redaction, rate limiting

## Quick Start

```bash
# Setup
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Run Postgres (Docker)
docker run -d --name saz-pg \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=saz \
  -p 5432:5432 postgres:16

# Environment variables
export DATABASE_URL="postgresql://postgres:secret@localhost/saz"
export CREDENTIALS_ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Setup database
alembic upgrade head

# Run API
uvicorn saz.api:app --reload --port 8000

# Run tests
pytest
```

## YAML DSL v1

### Structure

```yaml
flow:
  name: my_workflow
  version: "1.0"
  description: Workflow description

form:
  fields:
    - name: field_name
      type: text|number|boolean
      required: true
      regex: "^pattern$"  # For text fields
      min: 0  # For numbers
      max: 100

triggers:
  manual: true  # Enable manual runs
  schedule:
    cron: "0 9 * * *"  # Cron expression
  webhook:
    path: "/my-trigger"
    method: POST

workflow:
  steps:
    - id: step_1
      type: tool.call|condition|human.approval|webhook.wait|artifact.store|ai.assess
      tool: http_request  # For tool.call
      description: Step description
      params:
        # Tool-specific params with template expressions
        method: GET
        url: "{{ $form.api_url }}"
      expect:
        # JSON Schema for output validation
        type: object
        properties:
          status: {type: string}
      retry:
        attempts: 3
        backoff: linear|exponential
        max_delay: 30
      continue_on_fail: false

policies:
  budget:
    max_tokens: 100000
    max_cost_usd: 10.0
    max_steps: 50
    max_time_seconds: 3600
  rate_limits:
    max_requests_per_minute: 20
  pii:
    enforce_redaction: true
    allowed_fields: [email]

credentials:
  uses: [ssh_key, api_token]
```

### Step Types

| Type | Description | LLM Cost |
|------|-------------|----------|
| `tool.call` | Execute a tool (http, ansible, webhook, artifact) | $0 |
| `condition` | Boolean expression evaluation | $0 |
| `human.approval` | Suspend for manual approval | $0 |
| `webhook.wait` | Suspend until webhook callback | $0 |
| `artifact.store` | Store data as artifact | $0 |
| `artifact.retrieve` | Retrieve artifact by ID | $0 |
| `ai.*` | AI operations (13 types) - see below | ~$0.001-0.003 |

### AI Operations (First-Class AI Nodes)

**13 AI node types with strict contracts:**

| Node | Output | Temp | Use Case |
|------|--------|------|----------|
| `ai.assess` | JSON | 0.1 | Classify, extract, decide with confidence score |
| `ai.generate` | Text | 0.4 | Compose emails, summaries, messages (word cap) |
| `ai.plan` | JSON | 0.2 | Propose tool calls (tools allowlist enforced) |
| `ai.extract` | JSON | 0.1 | Pull structured fields from unstructured text |
| `ai.route` | JSON | 0.1 | Pick branch (enum enforced) |
| `ai.score` | JSON | 0.1 | Numeric scoring vs rubric (0-1 bounded) |
| `ai.normalize` | JSON | 0.1 | Canonicalize names, addresses, entities |
| `ai.match` | JSON | 0.1 | Entity resolution with top-k candidates |
| `ai.evaluate` | JSON | 0.1 | Guardrail QA (pass/fail with issues) |
| `ai.compare` | JSON | 0.1 | Semantic diff, duplicate detection |
| `ai.translate` | Text | 0.2 | Machine translate with glossary support |
| `ai.summarize` | Text | 0.2 | Compress text (word cap enforced) |
| `ai.fix_json` | JSON | 0.1 | Repair malformed JSON to schema (internal) |

**All AI ops:**
- Enforce JSON schema validation (auto-retry with `ai.fix_json` once)
- Log tokens + cost per call
- Support temperature/max_tokens overrides
- Response format: `{output, usage: {tokens, cost_usd}, metadata}`

**Example: ai.extract**
```yaml
- id: extract_data
  type: ai.extract
  instruction: "Extract customer name, email, and issue category"
  params:
    data:
      ticket: "{{ $form.ticket_text }}"
  schema:
    type: object
    properties:
      name: {type: string}
      email: {type: string}
      category: {type: string, enum: [bug, feature, support]}
    required: [name, email, category]
  temperature: 0.1
  max_tokens: 512
```

**Example: ai.route**
```yaml
- id: route_ticket
  type: ai.route
  instruction: "Route ticket to correct team"
  params:
    data:
      category: "{{ $step('extract').category }}"
      priority: "{{ $step('extract').priority }}"
  branches_enum: [engineering, support, sales, billing]
  temperature: 0.1
```

**Example: ai.generate**
```yaml
- id: generate_response
  type: ai.generate
  instruction: "Write professional acknowledgment email"
  params:
    data:
      customer: "{{ $step('extract').name }}"
      issue: "{{ $step('extract').category }}"
  word_cap: 200
  temperature: 0.4
```

**Example: ai.plan**
```yaml
- id: plan_actions
  type: ai.plan
  instruction: "Propose remediation steps for this incident"
  params:
    data:
      alert: "{{ $form.alert_type }}"
      severity: "{{ $form.severity }}"
  tools_allowlist: [http_request, ansible_run, webhook_emit]
  temperature: 0.2
  expect:
    type: object
    properties:
      calls:
        type: array
        items:
          type: object
          properties:
            tool: {type: string}
            args: {type: object}
            rationale: {type: string}
```

### Expression Syntax

**Variables:**
- `{{ $form.field_name }}` - Form field value
- `{{ $step('step_id').output_field }}` - Output from previous step
- `{{ $secret('credential_name') }}` - Inject encrypted credential
- `{{ $env('VAR_NAME') }}` - Environment variable

**Helpers:**
- `{{ coalesce($form.email, 'default@example.com') }}` - First non-null value
- `{{ toInt($form.age) }}` - Convert to integer
- `{{ lower($form.username) }}` - Lowercase
- `{{ upper($form.code) }}` - Uppercase
- `{{ len($form.items) }}` - Length

### Tools

#### HTTP Request
```yaml
- id: api_call
  type: tool.call
  tool: http_request
  params:
    method: GET|POST|PUT|DELETE
    url: "{{ $form.api_url }}"
    headers:
      Authorization: "Bearer {{ $secret('api_token') }}"
    body: {key: "value"}
    timeout: 30
```

#### Ansible
```yaml
- id: deploy
  type: tool.call
  tool: ansible_run
  params:
    mode: check|apply
    playbook: /path/to/playbook.yml
    inventory: /path/to/inventory
    limit: "webservers"
    tags: [deploy, config]
    extra_vars: {version: "1.2.3"}
    credentials:
      ssh_key: "{{ $secret('ansible_ssh_key') }}"
      vault_password: "{{ $secret('ansible_vault') }}"
    verbosity: 2
```

#### Webhooks
```yaml
# Emit webhook
- id: notify
  type: tool.call
  tool: webhook_emit
  params:
    url: "https://hooks.example.com/notify"
    method: POST
    body: {status: "completed"}

# Wait for webhook callback
- id: wait_approval
  type: webhook.wait
  params:
    timeout_seconds: 3600
```

#### Artifacts
```yaml
# Store artifact
- id: save_report
  type: artifact.store
  params:
    name: "report_{{ $env('TIMESTAMP') }}"
    content: {data: "{{ $step('generate').result }}"}

# Retrieve artifact
- id: load_report
  type: artifact.retrieve
  params:
    artifact_id: "{{ $form.artifact_id }}"
```

## Triggers

### Manual Trigger
```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "flow_id": "flow-uuid",
    "payload": {"field": "value"}
  }'
```

### Webhook Trigger
Flows with `triggers.webhook` expose an endpoint:
```bash
curl -X POST http://localhost:8000/webhooks/{flow_id}/trigger \
  -H "Content-Type: application/json" \
  -d '{"field": "value"}'
```

### Schedule Trigger (Cron)
Defined in YAML `triggers.schedule.cron`. Scheduler starts automatically.

### Resume Waiting Runs
For `webhook.wait` steps:
```bash
curl -X POST http://localhost:8000/runs/{run_id}/resume \
  -H "Content-Type: application/json" \
  -d '{"callback_data": "approved"}'
```

## Credentials

### Create Credential
```bash
curl -X POST http://localhost:8000/credentials \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my_api_token",
    "credential_type": "api_token",
    "data": {"token": "secret-value"},
    "description": "Production API token"
  }'
```

### List Credentials (Metadata Only)
```bash
curl http://localhost:8000/credentials
```

### Delete Credential
```bash
curl -X DELETE http://localhost:8000/credentials/my_api_token
```

**Security:**
- Encrypted at rest with Fernet (symmetric)
- Key from `CREDENTIALS_ENCRYPTION_KEY` env var
- Secrets never in API responses or logs
- Injected at runtime via `{{ $secret('name') }}`

## Execution History & Replay

### View Run Steps
```bash
curl http://localhost:8000/runs/{run_id}/steps
```

Returns full step history with inputs, outputs, errors, retry counts, artifacts.

### Replay from Step N
```bash
curl -X POST http://localhost:8000/runs/{run_id}/replay?from_step=2
```

Creates a new run with pinned inputs from original run's step history.

## Compliance API

### View Compliance Report
```bash
curl http://localhost:8000/runs/{run_id}/compliance
```

**Returns:**
```json
{
  "run_id": "...",
  "compliance": {
    "ai_usage": {
      "total_tokens": 1523,
      "total_cost_usd": 0.002284,
      "steps_count": 3,
      "steps": [
        {
          "step_name": "extract_data",
          "op": "ai.extract",
          "tokens": 412,
          "cost_usd": 0.000618,
          "temperature": 0.1,
          "model": "gpt-4o-mini"
        },
        ...
      ]
    },
    "budget": {
      "remaining_tokens": 98477,
      "remaining_cost": 9.997716,
      "remaining_steps": 47
    },
    "policy_violations": []
  }
}
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/register_forms` | Register flow from YAML |
| POST | `/runs` | Create run (manual trigger) |
| GET | `/runs/{id}` | Get run status |
| POST | `/runs/{id}/advance` | Advance suspended run |
| GET | `/runs/{id}/steps` | Get execution history |
| GET | `/runs/{id}/compliance` | Get compliance report (AI costs, budgets) |
| POST | `/runs/{id}/replay` | Replay from step N |
| POST | `/webhooks/{flow_id}/trigger` | Webhook trigger |
| POST | `/runs/{id}/resume` | Resume waiting run |
| POST | `/credentials` | Create credential |
| GET | `/credentials` | List credentials |
| DELETE | `/credentials/{name}` | Delete credential |

## Examples

See `examples/` for complete workflows:
- `http_conditional_flow.yaml` - HTTP API with conditional
- `approval_flow.yaml` - Human approval gate
- `ansible_approval_flow.yaml` - Ansible dry-run → approve → apply
- `ai_demo.yaml` - AI ops: extract → route → score → generate → evaluate
- `ai_plan_workflow.yaml` - AI planning: propose tool calls dynamically

## Structure

```
saz/
├── api.py                  # FastAPI endpoints + compliance API
├── agents/
│   ├── planner.py          # LLM planner (legacy)
│   ├── rule_planner.py     # Rule-based planner (default, $0 cost)
│   ├── ai_ops.py           # AI operations (13 node types)
│   ├── executor.py         # Tool grounding
│   └── critic.py           # Output validation
├── compiler/
│   └── compiler.py         # YAML → Pydantic + workflow spec
├── db/
│   ├── models.py           # SQLAlchemy models
│   ├── credentials.py      # Encrypted vault
│   └── session.py          # DB session
├── engine/
│   ├── workflow.py         # Workflow engine (vendored)
│   └── expressions.py      # Template resolver
├── policies/
│   ├── policy_engine.py    # Budget/PII/rate limit enforcement
│   ├── budget_tracker.py
│   ├── pii_detector.py
│   └── rate_limiter.py
├── tools/
│   ├── registry.py         # Tool discovery & execution (includes AI ops)
│   ├── http_tool.py
│   ├── ansible_tool.py
│   ├── webhook_tool.py
│   └── artifact_tool.py
└── triggers/
    └── scheduler.py        # Cron-based triggers
```

## Cost Discipline

**Default orchestration: $0 LLM cost**
Rule-based planner reads YAML steps directly. No LLM invocation for typical workflows (HTTP, Ansible, webhooks, conditions).

**AI operations: Pay-per-use with strict budgets**
- 13 AI node types (`ai.*`) - only these invoke LLM
- Forced JSON output with schema validation (auto-repair once via `ai.fix_json`)
- Temperature constraints (0.1-0.4) per operation type
- Cost per call: ~$0.001-0.003 with gpt-4o-mini (configurable via `LLM_MODEL` env)
- Token/$ tracking per step, aggregated in `/runs/{id}/compliance`

**Safety & monitoring:**
- Budget enforcement: max_tokens, max_cost_usd, max_steps per run
- PII redaction on inputs/outputs
- Rate limiting + HTTP domain allowlists
- Compliance API exposes: tokens, cost, temperature, model per AI step
- Replay any run from step N with pinned inputs

**Example costs (gpt-4o-mini):**
- `ai.extract` (512 tokens): ~$0.0008
- `ai.route` (256 tokens): ~$0.0004
- `ai.generate` (1024 tokens): ~$0.0015
- `ai.plan` (2048 tokens): ~$0.0031

**Total workflow cost typically < $0.01 for 5-7 AI steps.**