# Saz Frontend

Next.js 14 (App Router) UI for the Saz backend. TypeScript, Tailwind CSS,
TanStack React Query, Vitest. Renders flows, runs, events, and the human
approval / webhook callback panels.

See the [root README](../README.md) for what Saz is and the overall
repository layout.

## Architecture overview

```
frontend/
├── app/                # App Router pages
│   ├── flows/          # List, detail, new flow
│   ├── runs/           # List, detail (with step timeline + event stream)
│   ├── credentials/    # Credential management UI
│   ├── layout.tsx      # Root layout + providers
│   ├── providers.tsx   # React Query client
│   └── globals.css     # Tailwind
├── components/
│   ├── ui/             # Low-level primitives (button, tabs, switch, toast, ...)
│   ├── common/         # Shared layout / state cards / badges
│   ├── flows/          # Flow editor, template picker, AI ops panel
│   ├── runs/           # Run header, step timeline, approval/callback panels
│   ├── workflows/      # Workflow graph and live-overlay rendering
│   ├── metrics/        # Run metrics widgets
│   └── layout/         # Page chrome
├── lib/
│   ├── api.ts          # Typed API client (matches backend routes)
│   ├── types.ts        # Backend contract types
│   ├── types-enhanced.ts
│   ├── hooks.ts        # React Query hooks
│   ├── flows/, runs/   # Domain-scoped helpers
│   ├── use-*.ts        # Event/metric/error hooks
│   └── errors.ts, format-utils.ts, timeline-utils.ts
├── __tests__/          # Vitest tests (flows, runs)
├── vitest.config.ts
├── tsconfig.json
└── package.json
```

State flow: a page mounts → a React Query hook in `lib/hooks.ts` calls into
`lib/api.ts` → the API client hits the FastAPI backend → response is shaped
against `lib/types.ts`. Live updates for an open run come through the
`/api/v1/runs/{id}/stream` WebSocket via `lib/use-run-events.ts`.

## Install

Requirements: Node.js 20+ (CI uses Node 20) and npm.

```bash
cd frontend
npm ci
```

## Run locally

```bash
cp .env.local.example .env.local       # or .env.example for the full template
npm run dev
```

Open <http://localhost:3000>. The backend must be running and reachable at
`NEXT_PUBLIC_API_BASE_URL`.

## Configure the API URL

`frontend/.env.local`:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

`.env.example` documents optional Sentry variables
(`NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_SENTRY_ENABLED`, `SENTRY_ORG`,
`SENTRY_PROJECT`, `SENTRY_AUTH_TOKEN`). Sentry is disabled when DSN is empty.

The backend's CORS middleware allow-lists `http://localhost:3000` and
`http://127.0.0.1:3000`. Pointing the frontend at a different origin
requires updating that allow-list in `backend/saz/api/__init__.py`.

## Tests

Vitest is configured (`vitest.config.ts`) and tests live under `__tests__/`.
There is no `npm test` script yet; run Vitest directly:

```bash
npx vitest run            # run once
npx vitest                # watch mode
npx vitest run __tests__/runs/step-mapping.test.ts
```

CI does **not** run Vitest today — the frontend job runs typecheck, lint,
format check, and build. Frontend test execution is therefore a local
gate; keep tests passing before opening a PR.

## Typecheck, lint, build

```bash
npm run typecheck         # tsc --noEmit
npm run lint              # next lint
npm run format            # prettier --write
npm run format:check      # prettier --check
npm run build             # next build
npm run start             # serve the production build
```

These are the same scripts CI runs.

## Important directories

| Path                    | Purpose                                                                             |
| ----------------------- | ----------------------------------------------------------------------------------- |
| `app/flows/`            | Browse, create, and inspect flows. Uses Monaco for YAML editing.                    |
| `app/runs/`             | Run list and run detail (steps, events, approval, callback).                        |
| `app/credentials/`      | Credential CRUD UI.                                                                 |
| `components/runs/`      | Approval panel, webhook callback panel, step timeline, retry/replay UI.             |
| `components/workflows/` | Graph view (`@xyflow/react`) with live-event overlay.                               |
| `lib/api.ts`            | Single source of truth for backend HTTP calls.                                      |
| `lib/types.ts`          | TypeScript mirror of backend response/request shapes.                               |
| `lib/use-run-events.ts` | WebSocket subscription for run events.                                              |
| `__tests__/runs/`       | Run-page behavior tests (step mapping, live overlay, retry replay, callback panel). |
| `__tests__/flows/`      | Flow editor tests (template picker, AI ops panel/reference).                        |

## API contract alignment

Frontend types in `lib/types.ts` mirror backend Pydantic schemas in
`backend/saz/api/schemas/`. When changing an endpoint:

1. Update the Pydantic schema in `backend/saz/api/schemas/`.
2. Update or add the route in `backend/saz/api/routes/`.
3. Update the matching TypeScript type in `frontend/lib/types.ts`.
4. Update the call site in `frontend/lib/api.ts`.
5. Update components that read the new shape.
6. Update both backend tests and frontend tests.

Don't introduce a parallel field for the same concept on either side. Don't
leave legacy aliases unless they are explicitly needed and covered by tests.

## Limitations

- No authentication UI; the app assumes the backend is reachable and trusted
  on `localhost`.
- Live overlay relies on the backend WebSocket at
  `/api/v1/runs/{id}/stream`; if the socket drops, polling fallback is used
  to refresh canonical state from the DB.
- Some pages depend on optional backend env vars (e.g. AI ops require a
  configured LiteLLM provider). Steps surface clear errors when the backend
  is misconfigured.
