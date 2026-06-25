# Security Policy

Saz is a public prototype. There is no formal security support agreement,
no SLA, and no managed deployment. The notes below describe how to handle
secrets and how to report vulnerabilities.

## Supported versions

Only the current `main` branch is maintained. There are no long-term
support branches.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Report vulnerabilities privately via one of:

- GitHub's "Report a vulnerability" flow (Security tab → Advisories →
  New draft advisory), or
- A direct message to the repository maintainer through GitHub.

Include:

- A short description of the issue and its impact.
- Steps to reproduce (a minimal workflow YAML or curl recipe is ideal).
- The commit SHA you tested against.
- Any suggested mitigation, if you have one.

We will acknowledge the report and, if accepted, work with you on a fix
before any public disclosure. Best-effort timelines only — this is a
volunteer-maintained prototype.

## Do not commit secrets

The repository's `.gitignore` excludes `.env`, `.env*.local`, `*.secret`,
and `secrets/`. Commit `.env.example` files only.

Real values that must never land in version control:

- `OPENAI_API_KEY` and other LiteLLM provider keys.
- `CREDENTIALS_ENCRYPTION_KEY` (used to encrypt the `credentials` table).
- Database URLs containing live credentials.
- Tokens, signing keys, or webhook secrets used by deployed instances.

If a secret is committed by accident, rotate it immediately. A `git
revert` alone is not enough — assume the value is compromised the moment
it lands on a public branch.

## Credential handling

- The backend stores credentials symmetrically encrypted using
  `CREDENTIALS_ENCRYPTION_KEY`. Without that env var, credential
  features will refuse to operate or return errors — they will not fall
  back to plaintext.
- Audit events pass through `saz.audit.sanitizer` to redact known
  sensitive keys. PII detection and tokenization live in
  `saz.policies.pii_detector` and `saz.policies.pii_token_vault`.
- Treat anything in `Run.error` / `Step.error` as potentially
  caller-visible: do not store raw secrets there.

## API stack traces

`ALLOW_SENSITIVE_DATA` controls whether API errors may include stack
traces when explicitly requested. Keep it `false` everywhere except
local debugging.

## Authentication and authorization

- Authentication is local password or OIDC SSO. Authorization is a three-tier
  role per user — `viewer` (read-only), `operator`, `admin` — enforced in the
  backend dependency layer, not just the UI.
- Sessions are server-side: the access JWT carries a session id checked on every
  request, and a rotating HttpOnly refresh cookie keeps it alive. Logout,
  `logout_all`, disabling a user, password resets, and self password changes
  **revoke sessions immediately**.
- Run access is authorized per owner across REST and the WebSocket stream
  (admins see all). There is no multi-tenant isolation beyond per-run ownership
  and the role tiers; treat a deployment as single-tenant and single-team.

## Out of scope / operational cautions

- CORS is allow-listed via `ALLOWED_ORIGINS` (default `http://localhost:3000`,
  `http://127.0.0.1:3000`). Do not expose the API to the public internet without
  an upstream gateway, and set `COOKIE_SECURE=true` behind HTTPS.
- The Ansible tool is **fail-closed**: with no
  `SAZ_ANSIBLE_ALLOWED_PLAYBOOK_ROOTS` configured, every playbook is denied. The
  default registry scopes the allowlist to the bundled `examples/ansible` demo;
  set the variable (or `*` to allow all) only for playbooks you fully control.
- OIDC client secrets and stored credentials are encrypted at rest with
  `CREDENTIALS_ENCRYPTION_KEY`; without it those features refuse to operate
  rather than fall back to plaintext.
