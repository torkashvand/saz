# Saz - Complete Command Reference

## Initial Setup

```bash
# 1. Navigate to project
cd /Users/mohammad.torkashvand/www/saz

# 2. Create venv
python3.12 -m venv venv
source venv/bin/activate

# 3. Install
pip install -e ".[dev]"

# 4. Start PostgreSQL (Docker)
docker run -d --name saz-pg \
  -e POSTGRES_PASSWORD=secret \
  -e POSTGRES_DB=saz \
  -p 5432:5432 \
  postgres:16

# 5. Set environment
export DATABASE_URL="postgresql://postgres:secret@localhost/saz"

# 6. Run migrations
alembic upgrade head

# 7. Start API
uvicorn saz.api:app --reload --port 8000
```

## Run Tests

```bash
# All tests
pytest -v

# Specific test
pytest tests/test_integration.py::test_full_workflow -v

# With coverage
pytest --cov=saz --cov-report=html
```

## Database Commands

```bash
# Create migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1

# Reset database
alembic downgrade base
alembic upgrade head

# Connect to DB
psql postgresql://postgres:secret@localhost/saz
```

## API Testing

```bash
# Test with demo script
./examples/test_api.sh

# Manual curl commands
# 1. Register form
curl -X POST http://localhost:8000/register_forms \
  -H "Content-Type: application/json" \
  -d @- <<EOF
{
  "form_yaml": "$(cat examples/demo_form.yaml)"
}
EOF

# 2. Create run (replace FLOW_ID)
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "flow_id": "FLOW_ID_HERE",
    "payload": {
      "username": "testuser",
      "email": "test@example.com",
      "age": 25
    }
  }'

# 3. Get run status (replace RUN_ID)
curl http://localhost:8000/runs/RUN_ID_HERE

# 4. Advance run (replace RUN_ID)
curl -X POST http://localhost:8000/runs/RUN_ID_HERE/advance \
  -H "Content-Type: application/json" \
  -d '{"event": "continue"}'
```

## Docker Commands

```bash
# Stop containers
docker stop saz-pg saz-redis

# Remove containers
docker rm saz-pg saz-redis

# View logs
docker logs saz-pg
docker logs -f saz-redis

# Restart containers
docker restart saz-pg
```

## Production Deployment

```bash
# 1. Build
pip install build
python -m build

# 2. Install wheel
pip install dist/saz-0.1.0-py3-none-any.whl

# 3. Run with gunicorn
pip install gunicorn
gunicorn saz.api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# 4. Or use uvicorn directly
uvicorn saz.api:app --host 0.0.0.0 --port 8000 --workers 4
```

## Cleanup

```bash
# Stop API (Ctrl+C if running in foreground)

# Stop Docker containers
docker stop saz-pg saz-redis
docker rm saz-pg saz-redis

# Deactivate venv
deactivate

# Remove venv
rm -rf venv

# Drop database (if using local PostgreSQL)
dropdb saz
```
