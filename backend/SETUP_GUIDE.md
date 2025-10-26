# Saz Setup & Usage Guide

## Overview

Saz is a generic forms and workflows engine that combines:
- **YAML form definitions** → Pydantic v2 models
- **Orchestrator-core workflow engine** (vendored, domain-agnostic)
- **FastAPI service** for form registration and workflow execution
- **JSON Schema output** for UI rendering (pydantic-forms-ui compatible)

## Quick Start

### 1. Prerequisites

- Python 3.12+
- PostgreSQL 16 (or Docker)
- Redis 7 (optional, for future caching)

### 2. Installation

```bash
cd /Users/mohammad.torkashvand/www/saz

# Create virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 3. Database Setup

#### Option A: Docker (Recommended)

```bash
# Start PostgreSQL
docker run -d --name saz-pg \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=saz \
  -p 5432:5432 \
  postgres:16

# Start Redis (optional)
docker run -d --name saz-redis \
  -p 6379:6379 \
  redis:7
```

#### Option B: Local PostgreSQL

```bash
createdb saz
```

### 4. Run Migrations

```bash
export DATABASE_URL="postgresql://postgres:secret@localhost/saz"
alembic upgrade head
```

### 5. Start API Server

```bash
uvicorn saz.api:app --reload --port 8000
```

API will be available at: http://localhost:8000
Interactive docs: http://localhost:8000/docs

### 6. Run Tests

```bash
pytest -v
```

## Usage Examples

### Example 1: Register a Form

```bash
curl -X POST http://localhost:8000/register_forms \
  -H "Content-Type: application/json" \
  -d '{
    "form_yaml": "name: UserForm\nfields:\n  - name: username\n    type: text\n    required: true\n  - name: age\n    type: number\n    required: true\n    min: 18"
  }'
```

Response:
```json
{
  "flow_id": "123e4567-e89b-12d3-a456-426614174000",
  "name": "UserForm",
  "json_schema": {
    "type": "object",
    "properties": {
      "username": {"type": "string"},
      "age": {"type": "integer", "minimum": 18}
    },
    "required": ["username", "age"]
  }
}
```

### Example 2: Create a Workflow Run

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "flow_id": "123e4567-e89b-12d3-a456-426614174000",
    "payload": {
      "username": "john_doe",
      "age": 25
    }
  }'
```

Response:
```json
{
  "run_id": "456e7890-e89b-12d3-a456-426614174111",
  "status": "suspended",
  "state": {"username": "john_doe", "age": 25}
}
```

### Example 3: Advance a Run

```bash
curl -X POST http://localhost:8000/runs/456e7890-e89b-12d3-a456-426614174111/advance \
  -H "Content-Type: application/json" \
  -d '{"event": "continue"}'
```

Response:
```json
{
  "run_id": "456e7890-e89b-12d3-a456-426614174111",
  "status": "completed",
  "state": {"username": "john_doe", "age": 25, "approved": true}
}
```

### Example 4: Use Demo Script

```bash
# Uses examples/demo_form.yaml
./examples/test_api.sh
```

## UI Integration

### Option 1: pydantic-forms-ui

The JSON schema returned from `/register_forms` is compatible with pydantic-forms-ui.

1. Install pydantic-forms-ui in your frontend project:

```bash
npm install pydantic-forms-ui
```

2. Fetch the JSON schema:

```typescript
const response = await fetch('http://localhost:8000/register_forms', {
  method: 'POST',
  body: JSON.stringify({ form_yaml: '...' })
});
const { flow_id, json_schema } = await response.json();
```

3. Render the form:

```tsx
import { PydanticForm } from 'pydantic-forms-ui';

function MyForm({ jsonSchema, flowId }) {
  const handleSubmit = async (data) => {
    await fetch('http://localhost:8000/runs', {
      method: 'POST',
      body: JSON.stringify({ flow_id: flowId, payload: data })
    });
  };

  return <PydanticForm schema={jsonSchema} onSubmit={handleSubmit} />;
}
```

### Option 2: orchestrator-core-ui / example-orchestrator-ui

1. Point your UI at the Saz API:

```bash
cd /Users/mohammad.torkashvand/www/example-orchestrator-ui

# Update .env
echo "REACT_APP_API_URL=http://localhost:8000" > .env

npm install
npm start
```

2. The UI will automatically discover available forms via `/flows` endpoint (you may need to add this endpoint).

3. Forms will render dynamically based on JSON schema.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Saz System                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  YAML Forms (AnsibleForms style)                            │
│         ↓                                                    │
│  Compiler (YAML → Pydantic v2 + JSON Schema)               │
│         ↓                                                    │
│  Workflow Engine (vendored orchestrator-core)               │
│    - Process states (Success/Failed/Suspend/Complete)      │
│    - StepList execution                                     │
│    - State management                                       │
│         ↓                                                    │
│  FastAPI Service                                            │
│    - POST /register_forms                                   │
│    - POST /runs                                             │
│    - POST /runs/{id}/advance                               │
│    - GET /runs/{id}                                         │
│         ↓                                                    │
│  Database (PostgreSQL)                                      │
│    - flows (form definitions)                               │
│    - runs (workflow instances)                              │
│    - run_steps (step execution log)                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## YAML Form Schema

```yaml
name: MyForm
fields:
  - name: field_name
    type: text|number|float|boolean
    required: true|false
    description: "Field description"
    # Validation (optional):
    regex: "^pattern$"      # for text
    min: 0                  # for number/float
    max: 100                # for number/float
```

## YAML Workflow Schema

```yaml
description: "Workflow description"
steps:
  - name: step_name
    type: input|step      # input = suspend, step = execute
```

If no workflow YAML is provided, a default 2-step workflow is created:
1. `collect_form` (input step)
2. `approve` (approval step)

## Orchestrator-Core Components Used

### Vendored (Domain-Agnostic):
- `workflow.py` - Core engine (Process, Step, Workflow abstractions)
- Process states: Success, Failed, Suspend, Complete, Waiting
- Step decorators: `@step`, `@inputstep`, `@workflow`
- Workflow execution: `runwf()`

### Removed (Domain-Specific):
- Product/ProductBlock models
- Subscription models
- GraphQL endpoints
- Forms tied to subscriptions
- All domain-specific DB tables

## Development

### Project Structure

```
saz/
├── saz/
│   ├── __init__.py
│   ├── api.py                 # FastAPI service
│   ├── compiler/
│   │   ├── __init__.py
│   │   └── compiler.py        # YAML → Pydantic compiler
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py          # Database models
│   │   └── session.py         # DB session
│   └── engine/
│       ├── __init__.py
│       └── workflow.py        # Vendored workflow engine
├── alembic/
│   └── versions/
│       └── 001_initial_schema.py
├── examples/
│   ├── demo_form.yaml
│   ├── demo_workflow.yaml
│   └── test_api.sh
├── tests/
│   └── test_integration.py
├── pyproject.toml
├── alembic.ini
└── README.md
```

### Adding Custom Step Logic

By default, steps are placeholders. To add custom logic:

```python
# In compiler.py, modify create_workflow_from_yaml

@step("my_custom_step")
def my_custom_step(state: State) -> dict:
    # Your logic here
    result = some_processing(state)
    return {**state, "result": result}
```

## Troubleshooting

### Database Connection Issues

```bash
# Check if PostgreSQL is running
docker ps | grep saz-pg

# Check connection
psql postgresql://postgres:secret@localhost/saz -c "SELECT 1"
```

### Migration Issues

```bash
# Reset database
alembic downgrade base
alembic upgrade head

# Or recreate
dropdb saz && createdb saz
alembic upgrade head
```

### Import Errors

```bash
# Reinstall in editable mode
pip install -e ".[dev]"
```

## Next Steps

1. **Custom Step Implementations**: Add real business logic to workflow steps
2. **Authentication**: Add user authentication (OAuth2/OIDC)
3. **WebSocket Support**: Real-time workflow status updates
4. **Scheduler**: Periodic workflow execution
5. **UI Customization**: Build custom form renderer
6. **Metrics**: Add Prometheus metrics for workflow execution

## Comparison: Saz vs Orchestrator-Core

| Feature | Orchestrator-Core | Saz |
|---------|-------------------|------------|
| Domain Model | Product/Subscription | Generic (form-based) |
| Form Definition | Python classes | YAML |
| Workflow Engine | Full (GraphQL, API, CLI) | Core only (API) |
| DB Schema | 20+ tables | 3 tables |
| Dependencies | Heavy (Celery, Redis, etc.) | Light (FastAPI, SQLAlchemy) |
| Use Case | Telecom/network provisioning | General-purpose workflows |

## License

Same as orchestrator-core (Apache 2.0)
