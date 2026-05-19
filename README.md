# Saz

Workflow execution engine for operational automation. Workflows are defined in
YAML, compiled to a strict internal model, and executed with explicit policy
checks, audit events, human approvals, and webhook callbacks.

## What Saz does

- Parses and validates YAML workflows against a strict DSL (`schema_version: 1`).
- Executes workflows step-by-step against a real database with persisted runs,
  steps, attempts, errors, and audit events.
- Supports two planning modes:
  - **Deterministic** — steps run in the order written in YAML.
  - **Agentic** — an LLM planner generates the execution plan dynamically.
- Calls LLMs through [LiteLLM] for `ai.*` steps (extract, generate, classify)
  with strict output schemas.
- Runs deterministic tools (HTTP, webhook, artifact store, Ansible) through a
  central registry.
- Enforces budget, PII, and rate-limit policies before tool execution.
- Suspends on `human.approval` and `webhook.wait` and resumes via API.
- Emits structured audit events for every state transition.

## Key concepts

| Concept                   | Meaning                                                                                                                                              |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Workflow**              | A YAML document describing form inputs, policies, triggers, and a sequence of steps.                                                                 |
| **YAML DSL**              | The strict workflow schema (`schema_version: 1`). Compiled by `saz.compiler.dsl`.                                                                    |
| **Run**                   | A single execution of a workflow against a specific payload. Lifecycle: `queued → running → suspended? → completed` (or `failed`).                   |
| **Step**                  | A single unit inside a run. Carries `status`, `attempt`, `output`, and `error`.                                                                      |
| **Deterministic planner** | Translates `workflow.steps` 1:1 into an execution plan. No LLM is used to plan the graph.                                                            |
| **Agentic planner**       | LLM-driven planner that generates an execution plan from the DSL plus tool catalog.                                                                  |
| **Verifier / critic**     | Optional `CriticAgent` that inspects proposed step inputs before execution and step outputs after. Verdicts: `PASS`, `FAIL`, `REPLAN`, `ESCALATE`.   |
| **Policy checks**         | Budget, PII, and rate-limit enforcement applied before tool calls.                                                                                   |
| **Audit events**          | Structured events (`run.*`, `step.*`, `tool.*`, `approval.*`, `webhook.callback_received`, `policy.checked`) persisted and broadcast over WebSocket. |
| **Human approval**        | A `human.approval` step suspends the run until a caller approves or rejects via API.                                                                 |
| **Webhook callback**      | A `webhook.wait` step suspends until an external system POSTs to the generated callback URL.                                                         |
| **Tools**                 | Deterministic side-effecting actions exposed to the executor (HTTP, webhook, artifact, Ansible).                                                     |

## Repository structure

```
saz/
├── backend/                  # Python 3.12+ FastAPI service
│   ├── saz/
│   │   ├── api/              # FastAPI routers + Pydantic schemas
│   │   ├── agents/           # Planners, AI ops, critic, LLM port
│   │   ├── audit/            # Audit event bus, emitter, sanitizer
│   │   ├── compiler/         # YAML DSL compiler and template validator
│   │   ├── db/               # SQLAlchemy models, session, unit of work
│   │   ├── engine/           # Executor, scheduler, suspension sweeper
│   │   ├── examples/         # Bundled YAML workflows
│   │   ├── policies/         # Budget, PII, rate limit
│   │   ├── repositories/     # Read/write repository layer
│   │   ├── services/         # Flow, run, credential services
│   │   ├── tools/            # HTTP, webhook, artifact, Ansible
│   │   └── triggers/         # APScheduler trigger registry
│   ├── alembic/              # Migrations
│   ├── tests/                # Pytest suite (unit/services/integration/api/...)
│   └── pyproject.toml
├── frontend/                 # Next.js 14 + TypeScript app
│   ├── app/                  # App Router pages (flows, runs, credentials)
│   ├── components/           # UI components
│   ├── lib/                  # API client, hooks, types
│   └── __tests__/            # Vitest tests
├── .github/workflows/ci.yaml # Continuous integration
└── .pre-commit-config.yaml   # Root pre-commit hooks
```

## Quick start — backend

Requirements: Python 3.12+, [uv], and either SQLite (default) or PostgreSQL.

```bash
cd backend
uv sync                                  # install pinned dependencies
cp .env.example .env                     # set DATABASE_URL, OPENAI_API_KEY, etc.
uv run alembic upgrade head              # apply migrations
uv run uvicorn saz.api:app --reload --port 8000
```

API docs: <http://localhost:8000/api/v1/docs>

The default `DATABASE_URL` is `sqlite:///./saz.db`. Postgres is supported via a
`postgresql://...` URL.

## Quick start — frontend

Requirements: Node.js 20+ and npm.

```bash
cd frontend
npm ci
cp .env.local.example .env.local         # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev
```

UI: <http://localhost:3000>

The frontend expects the backend at `NEXT_PUBLIC_API_BASE_URL`. CORS is
allow-listed for `http://localhost:3000` in `backend/saz/api/__init__.py`.

## Tests

```bash
# Backend
cd backend
uv run pytest -n auto

# Frontend (vitest is installed; there is no npm script yet)
cd frontend
npx vitest run
```

Type checks, lint, format:

```bash
# Backend (ruff + mypy via pre-commit)
uv run --project backend pre-commit run --all-files

# Frontend
cd frontend
npm run typecheck
npm run lint
npm run format:check
```

## Example workflows

Bundled YAML workflows live in `backend/saz/examples/unified/`. They are loaded
automatically by the `TemplateManager` on backend start and listed at
`GET /api/templates/`. Start with `minimal_ai_step.yaml`; see
[`backend/saz/examples/README.md`](backend/saz/examples/README.md) for a
walkthrough of the demo workflows, including the human-approval and webhook
callback paths.

## Development workflow

1. Branch from `main`.
2. Make a focused change with tests in the same PR.
3. Run pre-commit and tests locally before pushing.
4. Open a PR against `main`. CI runs `backend` and `frontend` jobs on path
   changes and aggregates into a single required check (`CI / CI`).

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch/PR/test expectations.

## Configuration

Backend env vars (see `backend/.env.example`):

| Variable                                       | Default                       | Purpose                                                                                                       |
| ---------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                 | `sqlite:///./saz.db`          | SQLAlchemy connection URL.                                                                                    |
| `OPENAI_API_KEY`                               | (empty)                       | Used by LiteLLM when calling OpenAI models.                                                                   |
| `LLM_MODEL` / `PLANNER_MODEL` / `CRITIC_MODEL` | gpt-4o-mini / gpt-4o / gpt-4o | Default models for AI ops, planner, critic.                                                                   |
| `CREDENTIALS_ENCRYPTION_KEY`                   | (empty)                       | Symmetric key for stored credentials. Required for credential features.                                       |
| `ALLOW_SENSITIVE_DATA`                         | `false`                       | If `true`, the API may include stack traces when explicitly requested. Leave `false` outside local debugging. |
| `SUSPENSION_SWEEP_ENABLED`                     | `true`                        | Background sweeper that fails suspended runs past their deadline. Tests set this to `false`.                  |
| `SUSPENSION_SWEEP_INTERVAL_SECONDS`            | `60`                          | Sweep cadence.                                                                                                |
| `SUSPENSION_SWEEP_BATCH_LIMIT`                 | `100`                         | Max rows per sweep.                                                                                           |

LiteLLM picks up provider credentials from the standard environment variables
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Without a configured provider, any
`ai.*` step fails with a clear error.

Frontend env vars (see `frontend/.env.example`):

| Variable                                                  | Purpose                      |
| --------------------------------------------------------- | ---------------------------- |
| `NEXT_PUBLIC_API_BASE_URL`                                | Backend base URL.            |
| `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENABLED`, … | Optional Sentry integration. |

`.env` and `.env*.local` are gitignored; commit `.env.example` only.

## Status

Public prototype. Practical limitations to be aware of:

- No built-in authentication, RBAC, or multi-tenancy.
- CORS is hard-coded to `http://localhost:3000`.
- Background scheduler and suspension sweeper run in-process; there is no
  separate worker pool.
- The Ansible tool's path allowlist is empty by default (no allowlist = allow
  all). Set `SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS` before running untrusted
  playbooks.
- LLM cost and policy budgets are tracked but not billed.
- Templates ship as illustrative examples, not production-ready playbooks.

Treat the codebase as suitable for local evaluation, demos, and contributions.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Highlights:

- Small, focused PRs.
- Tests in the same PR as the change.
- Imperative commit subjects (`fix(api): validate flow registration`).

## Security

Do not commit secrets. To report a vulnerability, follow
[`SECURITY.md`](SECURITY.md). Credential and PII handling is documented in
[`backend/README.md`](backend/README.md#secrets-and-credentials).

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Copyright (c)
2026 Fariman Torkashvand.

[uv]: https://docs.astral.sh/uv/
[LiteLLM]: https://docs.litellm.ai/
