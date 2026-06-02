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
| **Workflow**              | A YAML document describing form inputs, policies, and a sequence of steps.                                                                           |
| **YAML DSL**              | The strict workflow schema (`schema_version: 1`). Compiled by `saz.compiler.dsl`.                                                                    |
| **Run**                   | A single execution of a workflow against a specific payload. Lifecycle: `queued → running → suspended? → completed` (or `failed`).                   |
| **Step**                  | A single unit inside a run. Carries `status`, `attempt`, `output`, and `error`.                                                                      |
| **Deterministic planner** | Translates `workflow.steps` 1:1 into an execution plan. No LLM is used to plan the graph (planning is $0); the verifier/critic may still run per step unless configured off, so a run is not necessarily LLM-free overall. |
| **Agentic planner**       | LLM-driven planner that generates an execution plan from the DSL plus tool catalog. Plans are bounded to the workflow's declared tools (`tool.call` steps + optional `workflow.allowed_tools`); an undeclared tool is blocked deterministically before execution, not just by the LLM verifier. |
| **Verifier / critic**     | Optional `CriticAgent` that inspects proposed step inputs before execution and step outputs after. Verdicts: `PASS`, `FAIL`, `REPLAN`, `ESCALATE`. Secrets are redacted from its prompts.   |
| **Policy checks**         | Budget, PII, and rate-limit enforcement applied before tool calls. Per-run isolated (no shared mutable state across concurrent runs).                 |
| **Audit events**          | Structured events (`run.*`, `step.*`, `tool.*`, `approval.*`, `critique.completed`, `webhook.callback_received`, `policy.blocked`, `policy.budget.exhausted`, `policy.rate_limited`, `artifact.created`) persisted with a monotonic per-run `seq` and broadcast over WebSocket. |
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
│   │   └── tools/            # HTTP, webhook, artifact, Ansible
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
cp .env.example .env                     # set DATABASE_URL, JWT_SECRET_KEY, ...
uv run alembic upgrade head              # apply migrations
uv run python -m saz.scripts.create_user \
    --username alice --email alice@example.com   # create the first user
uv run uvicorn saz.api.app:app --reload --port 8000
```

`JWT_SECRET_KEY` is required — leave it blank and login fails closed.
Generate one with `openssl rand -hex 32` or
`python -c "import secrets; print(secrets.token_hex(32))"`.

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
| `JWT_SECRET_KEY`                               | (empty)                       | HMAC secret used to sign access tokens. **Required** — login fails closed when empty.                          |
| `JWT_ALGORITHM`                                | `HS256`                       | JWT signing algorithm.                                                                                        |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`              | `720`                         | Access-token lifetime in minutes. No refresh tokens — users log in again after expiry.                        |

LiteLLM picks up provider credentials from the standard environment variables
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …). Without a configured provider, any
`ai.*` step fails with a clear error.

Frontend env vars (see `frontend/.env.example`):

| Variable                                                  | Purpose                      |
| --------------------------------------------------------- | ---------------------------- |
| `NEXT_PUBLIC_API_BASE_URL`                                | Backend base URL.            |
| `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENABLED`, … | Optional Sentry integration. |

`.env` and `.env*.local` are gitignored; commit `.env.example` only.

## Authentication and user management

Saz uses username/password login with JWT-based bearer tokens. User
creation and password recovery are intentionally admin-driven: there is
**no public registration** and **no public forgot-password flow**.

**Account model**

- Every account has two binary capability flags: `is_active` (can the
  user log in) and `is_admin` (can the user reach the admin user-
  management API/UI). There are no roles, no permission matrices, no
  teams, and no tenants.
- A `must_change_password` flag is flipped whenever an admin resets a
  user's password. While set, the backend blocks every operational
  endpoint for that user with HTTP 403 + `X-Password-Change-Required:
  true`; only `/auth/me` and `/auth/change_password` remain reachable.
  The frontend reads the flag and redirects the user to the
  change-password screen.

**Endpoints**

- `POST /api/v1/auth/login` — username-or-email + password → JWT.
- `GET  /api/v1/auth/me` — current user (allowed even while
  `must_change_password=true`).
- `POST /api/v1/auth/change_password` — self-service. Requires the
  current password so a stolen token alone cannot rotate it.
- `GET /POST /PATCH /api/v1/admin/users[/{id}/…]` — admin-only user
  management. Includes `set_active`, `set_admin`, and `reset_password`.

**Password recovery is admin-driven**

If a user forgets their password, an admin resets it from the admin
panel (or via `POST /api/v1/admin/users/{id}/reset_password`). The
admin hands the temporary password to the user out-of-band. The
backend marks the user as `must_change_password`; on next login the
user is forced to choose a new password before they can use Saz.

There is **no** "Forgot password?" link, no email reset, and no reset
token. The only paths to a working account are: ask an admin, or be
the admin (and the first admin is created via the CLI below).

**Other product non-goals (intentional):** no RBAC, no roles, no
permissions, no teams, no organizations, no tenants, no SSO/OIDC, no
OAuth, no invitation workflow, no billing, no enterprise IdP
integration. Do not market this as enterprise-identity-ready.

**Bootstrap the first admin (CLI)**

```bash
uv run python -m saz.scripts.create_user \
    --username alice --email alice@example.com
# password prompted interactively; defaults to creating an admin
```

After this admin exists, every subsequent user is created from the
**Admin → Users** screen (or `POST /api/v1/admin/users`). The CLI also
supports `--no-admin` and `--password` if you need it for scripted
deployments — but most operators should not use those.

**Operational notes**

- Passwords are stored as bcrypt hashes (cost 12). Plaintext passwords
  are never logged or returned by any endpoint.
- Token lifetime defaults to 12 hours. There are no refresh tokens or
  server-side session revocation yet — when the token expires the user
  signs in again.
- The WebSocket event stream accepts the same JWT as a query parameter
  (`?token=…`) because browsers cannot set headers on a WS upgrade. It is also
  authorized per run: a connection is refused unless the authenticated user
  owns the run (or is an admin), and raw user ids are not sent on the wire.
- Outbound HTTP tools (`http_request`, `webhook_emit`) are fail-closed: a
  request is denied unless its host is allow-listed, and allow-listed hosts
  that resolve to loopback/link-local (incl. cloud-metadata)/private/reserved
  addresses are blocked (SSRF protection).
- Resolved `$secret(...)` values are redacted before any verifier/critic LLM
  prompt, and before anything persisted, returned, or streamed.
- The webhook callback endpoint (`POST /api/v1/webhooks/callback/{id}`)
  intentionally remains public. It authenticates the caller via the
  unguessable callback id embedded in the URL, which is what external
  systems use to resume a suspended run. Treat that id as a credential.
- Admin user-management events (create/disable/reset/etc.) are emitted
  through structured logs (search for `audit=admin`). They never
  include plaintext passwords, password hashes, or JWTs.

## Status

Public prototype. Practical limitations to be aware of:

- Username/password authentication with JWT is available; admins
  create and manage users from an Admin panel and can reset another
  user's password (forcing the recipient to change it on next login).
  RBAC, multi-tenancy, SSO/OIDC, public registration, and
  forgot-password flows are intentionally not supported. All non-admin
  authenticated users currently have the same application-level access.
- CORS is hard-coded to `http://localhost:3000`.
- Background scheduler and suspension sweeper run in-process; there is no
  separate worker pool.
- The Ansible tool is fail-closed: by default only the bundled
  `examples/ansible` playbook root and demo inventory are allowed. Extend
  `SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS` to run playbooks elsewhere — there is
  no "allow all" default.
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
