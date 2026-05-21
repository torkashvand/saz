# Saz Backend

Python 3.12+ FastAPI service that compiles YAML workflows, executes runs,
enforces policies, and serves the API consumed by the frontend.

See the [root README](../README.md) for what Saz is and the overall
repository layout.

## Architecture overview

The backend is layered top-down:

```
HTTP request
  └─► FastAPI route (saz/api/routes/*)
        └─► Pydantic schema (saz/api/schemas/*)
              └─► Service (saz/services/*)
                    └─► Repository / Unit of Work (saz/repositories/*, saz/db/*)
                          └─► SQLAlchemy model (saz/db/models.py)

Run execution
  └─► Executor (saz/engine/executor.py)
        ├─► Planner (saz/agents/deterministic_planner.py | agentic_planner.py)
        ├─► AI ops (saz/agents/ai_ops.py via saz/agents/llm_port.py)
        ├─► Critic (saz/agents/critic.py)         # optional verifier
        ├─► Policy engine (saz/policies/*)        # budget / PII / rate limit
        ├─► Tools (saz/tools/*)                   # HTTP, webhook, artifact, ansible
        └─► Audit emitter (saz/audit/*)           # structured events
```

### Main modules

| Module                                                             | Responsibility                                                                                                                                               |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `saz.api`                                                          | FastAPI app factory, lifespan, CORS, error handlers, router registration.                                                                                    |
| `saz.api.routes`                                                   | HTTP endpoints for `flows`, `runs`, `templates`, `credentials`, `webhooks`, `stream` (WebSocket), `health`.                                                  |
| `saz.api.schemas`                                                  | Request/response Pydantic models per domain.                                                                                                                 |
| `saz.compiler.dsl`                                                 | YAML → strict workflow model. Enforces `schema_version: 1` and validates steps/forms/policies.                                                               |
| `saz.compiler.template_validator`                                  | Validates bundled example templates at startup.                                                                                                              |
| `saz.engine.executor`                                              | Run/step state machine; deterministic and agentic execution paths.                                                                                           |
| `saz.engine.scheduler`                                             | ThreadPoolExecutor-backed singleton that schedules queued runs for in-process execution.                                                                     |
| `saz.engine.suspension_sweeper`                                    | Background thread that fails suspended runs past their deadline.                                                                                             |
| `saz.engine.expressions` / `saz.engine.templating`                 | Step-input expression evaluation and templating.                                                                                                             |
| `saz.agents.deterministic_planner`                                 | 1:1 mapping from `workflow.steps` to execution plan.                                                                                                         |
| `saz.agents.agentic_planner`                                       | LLM-driven plan generation from DSL + tool catalog.                                                                                                          |
| `saz.agents.ai_ops`                                                | `ai.extract` / `ai.generate` / `ai.classify` with strict output schemas.                                                                                     |
| `saz.agents.critic`                                                | Pre- and post-execution verifier with `PASS / FAIL / REPLAN / ESCALATE` verdicts.                                                                            |
| `saz.agents.llm_port`                                              | Thin abstraction over LiteLLM so tests can swap in fakes.                                                                                                    |
| `saz.policies.policy_engine`                                       | Coordinates pre-call checks (budget, PII, rate limit).                                                                                                       |
| `saz.policies.pii_detector` / `pii_token_vault`                    | PII detection and tokenization.                                                                                                                              |
| `saz.policies.budget_tracker` / `rate_limiter`                     | Budget accounting and per-tool rate limits.                                                                                                                  |
| `saz.audit.event_emitter` / `event_bus` / `sanitizer`              | Structured event emission, in-process pub/sub, redaction.                                                                                                    |
| `saz.tools.*`                                                      | Deterministic side-effecting tools: `http_tool`, `webhook_tool`, `artifact_tool`, `ansible_tool`. The `registry` is the lookup surface used by the executor. |
| `saz.repositories.read` / `write`                                  | Read/write split repositories over SQLAlchemy.                                                                                                               |
| `saz.services.flow_service` / `run_service` / `credential_service` | Business logic between routes and repositories.                                                                                                              |
| `saz.db.models`                                                    | SQLAlchemy models (flows, runs, steps, events, credentials, …).                                                                                              |
| `saz.db.unit_of_work`                                              | Transactional unit-of-work wrapper.                                                                                                                          |

### Database

- SQLAlchemy 2.x models in `saz/db/models.py`.
- Migrations in `backend/alembic/`. Single baseline: `001_initial_schema.py`.
- Default URL is SQLite (`sqlite:///./saz.db`). PostgreSQL is supported via a
  `postgresql://...` URL. CI runs against `sqlite:///:memory:`.

## Install

Use [uv]:

```bash
cd backend
uv sync
```

This installs the runtime and dev dependency groups pinned in `uv.lock`.

Configure environment:

```bash
cp .env.example .env
# Edit DATABASE_URL, OPENAI_API_KEY, CREDENTIALS_ENCRYPTION_KEY as needed.
```

## Run migrations

```bash
uv run alembic upgrade head
```

To reset the local SQLite database:

```bash
uv run alembic downgrade base && uv run alembic upgrade head
```

To create a new migration after editing models:

```bash
uv run alembic revision --autogenerate -m "describe change"
```

## Run the API

```bash
uv run uvicorn saz.api.app:app --reload --port 8000
```

- Interactive docs: <http://localhost:8000/api/v1/docs>
- OpenAPI: <http://localhost:8000/api/v1/openapi.json>
- Health: <http://localhost:8000/health>

Mounted routers and prefixes:

| Prefix                     | Source                                                                |
| -------------------------- | --------------------------------------------------------------------- |
| `/`                        | `saz/api/routes/health.py` (root, `/health`)                          |
| `/api/v1/flows`            | `saz/api/routes/flows.py`                                             |
| `/api/v1/runs`             | `saz/api/routes/runs.py`                                              |
| `/api/v1/credentials`      | `saz/api/routes/credentials.py`                                       |
| `/api/v1/webhooks`         | `saz/api/routes/webhooks.py` (`/runs/{id}/resume`, callback endpoint) |
| `/api/v1/runs/{id}/stream` | `saz/api/routes/stream.py` (WebSocket events)                         |
| `/api/templates`           | `saz/api/routes/templates.py` (read-only bundled examples)            |

## Run tests

Always use `-n auto` for the full suite.

```bash
# Full suite (parallel)
uv run pytest -n auto

# A single layer
uv run pytest -n auto tests/unit
uv run pytest -n auto tests/services
uv run pytest -n auto tests/api
uv run pytest -n auto tests/integration
uv run pytest -n auto tests/contracts
uv run pytest -n auto tests/examples
uv run pytest -n auto tests/acceptance
uv run pytest -n auto tests/regression

# A single file
uv run pytest -n auto tests/unit/test_executor.py
```

CI (`.github/workflows/ci.yaml`) runs `uv run pytest -n auto -q` against an
in-memory SQLite (`DATABASE_URL=sqlite:///:memory:`) with the suspension
sweeper disabled.

### Coverage

`coverage` is configured in `pyproject.toml` and a helper script asserts
per-package thresholds.

```bash
# Coverage requires -n 0 (pytest-xdist + coverage need extra wiring).
uv run coverage run -m pytest -n 0
uv run python scripts/check_coverage.py   # asserts per-package thresholds
uv run coverage report                    # text report
uv run coverage html                      # htmlcov/
```

Thresholds (see `scripts/check_coverage.py`):

| Path                | Min branch coverage |
| ------------------- | ------------------- |
| `saz/compiler/`     | 95%                 |
| `saz/agents/`       | 90%                 |
| `saz/engine/`       | 90%                 |
| `saz/policies/`     | 90%                 |
| `saz/api/routes/`   | 85%                 |
| `saz/repositories/` | 80%                 |
| `saz/tools/`        | 80%                 |

## Example workflows

Bundled YAML workflows live in `saz/examples/unified/` and are loaded into the
`TemplateManager` at startup, then exposed at `GET /api/templates/`. The
catalog includes:

- `minimal_ai_step.yaml` — simplest AI-only flow.
- `incident_triage.yaml` — AI classification + audit artifact.
- `change_approval_ansible.yaml` — AI summary → Ansible check → human approval → Ansible apply.
- `callback_driven_maintenance.yaml` — suspend on `webhook.wait`, resume via external callback.
- `http_summary_report.yaml`, `support_ticket_webhook.yaml`,
  `pii_safe_support_demo.yaml`, `procurement_*` — additional scenarios.

See [`saz/examples/README.md`](saz/examples/README.md) for a walkthrough of the
demo flows.

## Testing expectations

The test tree mirrors the architecture:

```
tests/unit/         pure logic, validators, small policy functions
tests/services/     service-layer behavior
tests/api/          FastAPI route contracts
tests/integration/  executor + tools + repositories with realistic fakes
tests/contracts/    OpenAPI / DSL / audit event contracts
tests/examples/     example YAML validity and drift protection
tests/acceptance/   operator flows across API/runtime/DB/audit
tests/regression/   regressions captured as standalone tests
tests/fakes/        FakeCritic, FakeTools, FakeLLM used across layers
```

When changing runtime behavior, assert both final state and important
intermediate side effects:

- `Run.status`, `Step.status`, `Step.attempt`
- `Step.output`, `Step.error`, `Run.error`
- emitted audit events
- tool calls made or not made
- retry numbering and resume semantics

For safety changes (policy, verifier, PII, credentials), assert that unsafe
side effects did **not** occur (tool not called, secrets not exposed, audit
event emitted, run not left half-running).

See the root [`CLAUDE.md`] for the full conventions if you have access; the
quick rules are: prefer real models + fakes over deep mock chains, do not
mock away the executor in tests whose subject is the executor, and cover
negative paths (invalid YAML, schema-invalid AI output, blocked tool, late
callback, suspension timeout).

[`CLAUDE.md`]: ../.claude/CLAUDE.md

## LLM calls in tests

`ai.*` steps go through `saz.agents.llm_port.LLMPort`, a thin abstraction
over LiteLLM.

- Unit, service, integration, and acceptance tests must use the in-tree fakes
  (`tests/fakes/`) rather than calling real LLMs. No test should issue a
  network request to a model provider.
- `LLM_MODEL`, `PLANNER_MODEL`, and `CRITIC_MODEL` are not consulted by tests
  that swap in a fake `LLMPort`.
- Anything that requires a real provider should be marked as external/manual
  and excluded from the default suite.

When the API server runs locally with `OPENAI_API_KEY` set (or any other
LiteLLM-supported provider key), real model calls are made for `ai.*` steps.
Without a key, those steps fail with a clear, structured error.

## Secrets and credentials

- The `credentials` table stores secrets symmetrically encrypted with
  `CREDENTIALS_ENCRYPTION_KEY`. Set this before exercising credential flows.
- Audit events are passed through `saz.audit.sanitizer` to redact known
  sensitive keys. PII handling is delegated to `saz.policies.pii_detector`
  and `pii_token_vault`.
- `ALLOW_SENSITIVE_DATA` controls whether the API may include stack traces
  when explicitly requested. Keep it `false` outside local debugging.
- Never commit real keys. Use `.env.example` as the template; `.env` is
  gitignored.

## Limitations

- Username/password authentication with JWT is implemented. Admins
  can create, disable, reactivate, promote/demote, and reset other
  users' passwords from `/api/v1/admin/users`; admin password resets
  force the user to change their password on next login. RBAC,
  multi-tenant isolation, SSO/OIDC, public registration, and
  forgot-password flows are intentionally not implemented — every
  authenticated non-admin user has the same application-level access.
- Scheduler and suspension sweeper run in-process; restart loses any
  in-memory state.
- The Ansible tool's playbook-path allowlist defaults to empty (all paths
  allowed). Set `SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS` before running playbooks
  you do not own.
- LLM cost and policy budgets are tracked, not billed.

[uv]: https://docs.astral.sh/uv/
