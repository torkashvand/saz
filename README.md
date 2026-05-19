# Saz - Monorepo

YAML forms + workflow engine (Python backend + Next.js frontend).

## Structure

```
saz/
├── backend/          # Python FastAPI + orchestrator-core
└── frontend/         # Next.js 14 + TypeScript + TailwindCSS
```

## Quick Start (Full Stack)

### 1. Start Backend

```bash
cd backend

# Setup Python environment
python3.12 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Start PostgreSQL (Docker)
docker run -d --name saz-pg \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=saz \
  -p 5432:5432 \
  postgres:16

# Setup database
export DATABASE_URL="postgresql://postgres:secret@localhost/saz"
alembic upgrade head

# Start API
uvicorn saz.api:app --reload --port 8000
```

Backend runs on http://localhost:8000

### 2. Start Frontend

```bash
# In new terminal
cd frontend

# Install dependencies
npm install

# Create environment
cp .env.local.example .env.local

# Start dev server
npm run dev
```

Frontend runs on http://localhost:3000

## 2-Minute Test

1. **Backend**: Verify API at http://localhost:8000/docs
2. **Frontend**: Open http://localhost:3000
3. **Register**: Go to /register, click "Load Example", click "Register & Preview"
4. **Run**: Click "Create Run", fill form, submit
5. **Advance**: On run detail page, click "Advance Workflow"

## Documentation

- `backend/README.md` - Backend setup & API docs
- `frontend/README.md` - Frontend setup & usage
- `backend/SETUP_GUIDE.md` - Detailed backend guide
- `backend/DELIVERABLE.md` - Complete technical docs

## Architecture

```
Frontend (Next.js)
    ↓ HTTP
Backend (FastAPI)
    ↓ SQL
Database (PostgreSQL)
```

**Flow:**
1. User pastes YAML → Backend compiles to Pydantic model
2. User submits form → Backend validates & creates workflow run
3. User clicks advance → Backend executes next workflow step
4. Frontend polls for updates → Shows real-time status

## Tech Stack

**Backend:**
- FastAPI
- Pydantic v2
- SQLAlchemy
- PostgreSQL
- Vendored orchestrator-core workflow engine

**Frontend:**
- Next.js 14 (App Router)
- TypeScript
- TailwindCSS + shadcn/ui
- TanStack Query
- Monaco Editor

## Development

**Backend tests:**
```bash
cd backend
pytest -v
```

**Frontend build:**
```bash
cd frontend
npm run build
```

## Continuous Integration

GitHub Actions workflow: `.github/workflows/ci.yaml`.

**Runs on:** pull requests targeting `main`, and pushes to `main`.

**What runs (only when the matching paths change):**

Backend (`backend/**`, `pyproject.toml`, `uv.lock`):
1. `uv sync` — install pinned dependencies.
2. `uv run pre-commit run --all-files` — ruff lint + ruff-format + uv-lock check.
3. `uv run mypy .` — strict type check.
4. `uv run pytest -n auto -q` — full test suite (parallel).

Frontend (`frontend/**`):
1. `npm ci`
2. `npm run typecheck`
3. `npm run lint`
4. `npm run format:check`
5. `npm run build`

A final `CI` job aggregates the per-area results. PRs must show a green
`CI / CI` check before merge. Set this as the required status check in
GitHub branch protection — it succeeds whether backend, frontend, or
both ran, and fails on any failure or cancellation.

## Environment Variables

**Backend** (`.env` or export):
```bash
DATABASE_URL=postgresql://postgres:secret@localhost/saz
```

**Frontend** (`frontend/.env.local`):
```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Production

**Backend:**
```bash
cd backend
gunicorn saz.api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

**Frontend:**
```bash
cd frontend
npm run build
npm run start
```

## CORS Configuration

If frontend is on different domain, update backend API:

```python
# backend/saz/api.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Troubleshooting

**Backend won't start:**
- Check PostgreSQL is running: `docker ps | grep saz-pg`
- Verify DATABASE_URL: `echo $DATABASE_URL`
- Run migrations: `cd backend && alembic upgrade head`

**Frontend can't connect:**
- Check backend is running on port 8000
- Verify `.env.local` has correct API URL
- Check browser console for CORS errors

**Database errors:**
- Reset: `cd backend && alembic downgrade base && alembic upgrade head`

## License

Apache 2.0
