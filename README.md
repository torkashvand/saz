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
│   ├── app/                  # App Router pages (flows, runs, credentials, login, admin)
│   ├── components/           # UI components
│   ├── lib/                  # API client, hooks, types
│   └── __tests__/            # Vitest tests
├── .github/workflows/ci.yaml # Continuous integration
└── .pre-commit-config.yaml   # Root pre-commit hooks
```

## Quick start — backend

Requirements: Python 3.12+, [uv], and a reachable **PostgreSQL** database (Saz
is PostgreSQL-only — there is no SQLite fallback).

```bash
cd backend
uv sync                                  # install pinned dependencies
cp .env.example .env                     # set DATABASE_URL, JWT_SECRET_KEY, ...
uv run alembic upgrade head              # apply migrations
uv run python -m saz.scripts.create_user \
    --username alice --email alice@example.com   # create the first admin
uv run uvicorn saz.api.app:app --reload --port 8000
```

`JWT_SECRET_KEY` is required — leave it blank and login fails closed.
Generate one with `openssl rand -hex 32` or
`python -c "import secrets; print(secrets.token_hex(32))"`.

API docs: <http://localhost:8000/api/v1/docs>

`DATABASE_URL` must be a PostgreSQL URL (e.g.
`postgresql+psycopg2://saz:saz@localhost:5432/saz_db`). The application and the
test suite both rely on PostgreSQL semantics (foreign-key enforcement, JSON,
transactional DDL).

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
# Backend (requires a reachable PostgreSQL cluster; each xdist worker
# creates and drops its own isolated database — see backend/README.md)
cd backend
uv run pytest -n auto

# Frontend
cd frontend
npm run test            # vitest run
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

| Variable                                       | Default                                              | Purpose                                                                                                       |
| ---------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`                                 | `postgresql+psycopg2://saz:saz@localhost:5432/saz_db` | SQLAlchemy connection URL. Must be PostgreSQL.                                                               |
| `OPENAI_API_KEY`                               | (empty)                                              | Used by LiteLLM when calling OpenAI models.                                                                   |
| `LLM_MODEL` / `PLANNER_MODEL` / `CRITIC_MODEL` | gpt-4o-mini / gpt-4o / gpt-4o                        | Default models for AI ops, planner, critic.                                                                   |
| `CREDENTIALS_ENCRYPTION_KEY`                   | (empty)                                              | Fernet key for stored credentials **and** encrypted OIDC client secrets. Required for those features.        |
| `ALLOW_SENSITIVE_DATA`                         | `false`                                              | If `true`, the API may include stack traces when explicitly requested. Leave `false` outside local debugging. |
| `ALLOWED_ORIGINS`                              | `http://localhost:3000,http://127.0.0.1:3000`        | Comma-separated browser origins permitted to call the API (CORS).                                            |
| `SUSPENSION_SWEEP_ENABLED`                     | `true`                                               | Background sweeper that fails suspended runs past their deadline. Tests set this to `false`.                  |
| `SUSPENSION_SWEEP_INTERVAL_SECONDS`            | `60`                                                 | Sweep cadence.                                                                                                |
| `SUSPENSION_SWEEP_BATCH_LIMIT`                 | `100`                                                | Max rows per sweep.                                                                                           |
| `JWT_SECRET_KEY`                               | (empty)                                              | HMAC secret used to sign access tokens. **Required** — login fails closed when empty.                          |
| `JWT_ALGORITHM`                                | `HS256`                                              | JWT signing algorithm.                                                                                        |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`              | `720`                                                | Access-token lifetime in minutes. A rotating HttpOnly refresh cookie keeps the session alive past this.       |
| `REFRESH_COOKIE_NAME`                          | `saz_refresh`                                        | Name of the HttpOnly refresh-session cookie.                                                                  |
| `SESSION_IDLE_TIMEOUT_DAYS` / `SESSION_ABSOLUTE_TIMEOUT_DAYS` | `7` / `30`                             | Refresh-session idle and absolute lifetimes.                                                                 |
| `COOKIE_SECURE` / `COOKIE_SAMESITE`            | `false` / `lax`                                      | Refresh-cookie flags. Set `COOKIE_SECURE=true` behind HTTPS.                                                  |
| `BACKEND_BASE_URL` / `FRONTEND_BASE_URL`       | `http://localhost:8000` / `http://localhost:3000`    | Public base URLs, used to build the OIDC redirect URI and post-login redirects.                              |

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

Saz authenticates with either a local username/password or **OIDC single
sign-on**, and authorizes every request against a per-user **role**. Account
creation and password recovery are intentionally admin-driven: there is **no
public registration** and **no public forgot-password flow**.

**Roles (RBAC)**

Every account has one `role`, the single source of truth for what it may do,
enforced in the FastAPI dependency layer (not just the UI):

- `viewer` — read-only. May reach GET endpoints; mutating endpoints return
  HTTP 403 (`write access required`).
- `operator` — the default tier. Run and manage workflows.
- `admin` — everything `operator` can do, plus user management and SSO-provider
  configuration.

`is_active` (can the user log in) is independent of role. A
`must_change_password` flag is flipped whenever an admin resets a password;
while set, the backend blocks every operational endpoint with HTTP 403 +
`X-Password-Change-Required: true`, leaving only `/auth/me` and
`/auth/change_password` reachable, and the frontend redirects to the
change-password screen.

**Sessions and tokens**

Login returns a short-lived access JWT and sets a rotating **HttpOnly refresh
cookie** bound to a server-side `auth_sessions` row:

- The access token carries a `sid` claim checked against the session row on
  every request, so a revoked session is rejected immediately even before the
  access token expires.
- `POST /auth/refresh` rotates the refresh secret; replaying an already-rotated
  secret is treated as theft and revokes the whole session.
- Sessions are revoked on logout, on `logout_all`, when an admin disables a
  user or resets their password, and on a self password change (other devices).
- A user can list and revoke their own sessions (`/auth/sessions`); an admin
  can list and revoke any user's sessions (`/admin/users/{id}/sessions`).

**OIDC single sign-on**

Identity providers are stored in the database and managed under **Admin → SSO**
(`/api/v1/admin/auth/providers`). The flow is Authorization Code + PKCE:

- The client secret is optional (public/PKCE clients) and, when present, stored
  Fernet-encrypted and write-only (never returned).
- Profile/email are read from the provider's UserInfo endpoint; a per-provider
  `trust_email_verified` flag covers IdPs (e.g. GEANT/eduGAIN) that release an
  email but never set `email_verified`.
- Just-in-time provisioning (optional, per provider) creates a new account at a
  configurable default tier (`viewer` or `operator`) — it can never mint an
  admin. Local password login always remains available as a break-glass path.

**Key endpoints**

- `POST /api/v1/auth/login` — username-or-email + password → access token + refresh cookie.
- `POST /api/v1/auth/refresh` · `POST /api/v1/auth/logout` · `POST /api/v1/auth/logout_all`
- `GET /DELETE /api/v1/auth/sessions[/{id}]` — the caller's own sessions.
- `GET  /api/v1/auth/me` · `POST /api/v1/auth/change_password` (requires the current password).
- `GET  /api/v1/auth/providers` — public list of enabled SSO providers for the login screen.
- `GET  /api/v1/auth/oidc/{provider}/start` · `GET /api/v1/auth/oidc/callback` — the SSO flow.
- `GET /POST /PATCH /api/v1/admin/users[/{id}/…]` — admin-only user management
  (`set_active`, `set_role`, `reset_password`, `sessions`).
- `GET /POST /PATCH /DELETE /api/v1/admin/auth/providers[/{id}/test]` — admin-only SSO config.

**Password recovery is admin-driven**

If a user forgets their password, an admin resets it (`POST
/api/v1/admin/users/{id}/reset_password`) and hands the temporary password over
out-of-band; the user is marked `must_change_password` and must choose a new one
on next login. There is **no** "Forgot password?" link, no email reset, and no
reset token.

**Product non-goals (intentional):** no public registration, no
forgot-password flow, no multi-tenancy/teams/organizations, no per-resource
ACLs beyond the three role tiers, no billing. Authorization is a single role
tier per user, not a permissions matrix.

**Bootstrap the first admin (CLI)**

```bash
uv run python -m saz.scripts.create_user \
    --username alice --email alice@example.com
# password prompted interactively; creates an admin by default
```

After this admin exists, every subsequent user is created from the
**Admin → Users** screen (or `POST /api/v1/admin/users`), or provisioned via
SSO. The CLI also supports `--no-admin` and `--password` for scripted
deployments.

**Operational notes**

- Passwords are stored as bcrypt hashes (cost 12). Plaintext passwords
  are never logged or returned by any endpoint.
- Access-token lifetime defaults to 12 hours; the rotating refresh cookie keeps
  a session alive (subject to the idle/absolute timeouts) and revocation is
  immediate via the per-request session check.
- Run access is authorized per run across both transports: the REST run
  endpoints (`GET /runs`, `/runs/{id}`, `/runs/{id}/events`, `/steps`,
  `/graph`, `/summary`, `/compliance`, retry) and the WebSocket event stream
  all refuse a run the authenticated user does not own (admins see all). The
  WS stream accepts the JWT as a query parameter (`?token=…`) because browsers
  cannot set headers on a WS upgrade; raw user ids are not sent on the wire.
- Outbound HTTP tools (`http_request`, `webhook_emit`) are fail-closed: a
  request is denied unless its host is allow-listed, and allow-listed hosts
  that resolve to loopback/link-local (incl. cloud-metadata)/private/reserved
  addresses are blocked (SSRF protection). Redirects are not followed. The
  guard validates the resolved IP before the request, but `httpx` re-resolves
  at connect time, so a *residual* DNS-rebinding (TOCTOU) risk remains; pair
  the allowlist with trusted DNS for sensitive deployments.
- HTTP responses are scrubbed before they are persisted: sensitive response
  headers (`Set-Cookie`, `WWW-Authenticate`, `X-Api-Key`, …) and
  credential-named body fields are redacted. This is best-effort for secrets
  an upstream echoes back, not a guarantee.
- PII and resolved `$secret(...)` values are redacted before any planner /
  verifier / critic LLM prompt (under the default `pii.allow: false`), and
  secrets are redacted before anything persisted, returned, or streamed. Audit
  event summaries are sanitized too, not just payloads.
- The webhook callback endpoint (`POST /api/v1/webhooks/callback/{id}`)
  intentionally remains public. It authenticates the caller via the
  unguessable callback id embedded in the URL, which is what external
  systems use to resume a suspended run. Treat that id as a credential.
- Admin user-management events (create/disable/reset/etc.) are emitted
  through structured logs (search for `audit=admin`). They never
  include plaintext passwords, password hashes, or JWTs.

## Status

Public prototype. Practical limitations to be aware of:

- Authentication supports local password and OIDC SSO, with a three-tier role
  model (`viewer` / `operator` / `admin`), server-side refresh sessions with
  immediate revocation, and admin-driven user and SSO-provider management.
  Multi-tenancy, public registration, and forgot-password flows are
  intentionally not supported.
- CORS origins are configured via `ALLOWED_ORIGINS` (default
  `http://localhost:3000`, `http://127.0.0.1:3000`).
- Background scheduler and suspension sweeper run in-process; there is no
  separate worker pool.
- The Ansible tool is fail-closed: by default only the bundled
  `examples/ansible` playbook root and demo inventory are allowed. Extend
  `SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS` to run playbooks elsewhere — there is
  no "allow all" default.
- LLM cost and policy budgets are tracked but not billed. In agentic mode the
  budget is checked before the first planning call, so an exhausted budget
  stops planning.
- Conditional execution is via an opt-in per-step `when:` guard — when it
  evaluates false the step is skipped (status `skipped`, no side effects, a
  `step.skipped` event). The `condition` step type computes a boolean flag for
  downstream use; it does not itself branch.
- `human.approval`: `approvers` (usernames/emails) is enforced on the
  authenticated `POST /runs/{id}/resume` path; a non-approver gets 403.
  `approver_role` is surfaced as metadata but not enforced (there is no role
  system). The public webhook callback URL is a capability and is not gated by
  `approvers`.
- `webhook.wait`: when a callback provides an `event_name` it must match the
  awaited event or the callback is rejected.
- `policies.concurrency` (`per_flow` / `per_user`) is accepted by the compiler
  but **not yet enforced** at runtime — treat it as reserved.
- Templates ship as illustrative examples, not production-ready playbooks. They
  compile and register; only examples covered by an end-to-end execution test
  are validated as runnable.

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
