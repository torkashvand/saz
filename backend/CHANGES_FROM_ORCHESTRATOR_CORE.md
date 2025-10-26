# Changes from Orchestrator-Core

This document details what was removed from orchestrator-core to make it domain-agnostic for Saz.

## Files Removed (Domain-Specific)

### Entire Directories Removed:
- `domain/` - ProductBlockModel, SubscriptionModel, lifecycle management
- `graphql/` - GraphQL API tied to subscriptions
- `api/api_v1/` - REST endpoints for products/subscriptions
- `forms/validators/` - Subscription-specific validators
- `cli/` - CLI tools for product/subscription management
- `services/` (most) - Product/subscription services
- `metrics/` - Subscription-specific metrics
- `search/` - Subscription search functionality
- `schedules/` - Task scheduling (Celery-based)

### Specific Files Removed:
- `domain/base.py` - ProductBlockModel, SubscriptionModel base classes
- `domain/lifecycle.py` - Product lifecycle management
- `domain/customer_description.py` - Customer descriptions
- `domain/subscription_instance_transform.py` - Subscription transformations
- `domain/helpers.py` - Domain-specific helpers
- `services/products.py` - Product service layer
- `services/subscriptions.py` - Subscription service layer
- `services/processes.py` - Process management (DB-coupled)

## Database Schema Changes

### Tables Removed:
- `products` - Product catalog
- `product_blocks` - Product block definitions
- `product_block_relations` - Product block hierarchy
- `resource_types` - Resource type definitions
- `product_block_resource_types` - Many-to-many association
- `fixed_inputs` - Product fixed inputs
- `subscriptions` - Subscription instances
- `subscription_instances` - Subscription instance tree
- `subscription_instance_values` - Instance values
- `subscription_instance_relations` - Instance hierarchy
- `subscription_customer_descriptions` - Customer descriptions
- `subscription_metadata` - Subscription metadata
- `subscriptions_search` - Search materialized view
- `products_workflows` - Product/workflow association
- `processes_subscriptions` - Process/subscription link

### Tables Kept (Generic Workflow):
- `workflows` - Workflow definitions (KEPT, but simplified)
- `processes` - Workflow runs (KEPT, renamed to `runs`)
- `process_steps` - Step execution log (KEPT, renamed to `run_steps`)
- `input_states` - Input states (REMOVED - not needed for simple case)

### New Tables:
- `flows` - Registered form/workflow definitions
- `runs` - Workflow run instances (replaces `processes`)
- `run_steps` - Step execution log (replaces `process_steps`)

## Code Changes

### workflow.py (Vendored & Simplified)

**Removed:**
- Celery integration
- `pydantic_forms` dependency (kept simple State dict)
- Subscription/Product context injection
- `Assignee` enum (removed user assignment)
- Auth callbacks
- Retry mechanisms
- Step groups
- Callback steps
- Conditional steps
- Focus steps
- DB transaction management
- Websocket broadcasting

**Kept:**
- Core Process ADT (Success/Failed/Suspend/Complete/Waiting)
- Step/StepList/Workflow protocols
- Decorators: @step, @inputstep, @workflow
- Pure workflow execution logic (runwf)
- ProcessStat dataclass

**Simplified:**
- Removed transactional DB wrapper (now handled in API layer)
- Removed structlog context binding
- Removed engine settings check (global lock)
- Removed complex error handling (simplified)

### API Changes

**Old (orchestrator-core):**
- `/api/processes` - Create/manage processes for subscriptions
- `/api/products` - Product CRUD
- `/api/subscriptions` - Subscription CRUD
- `/api/workflows` - Workflow management
- GraphQL endpoint

**New (saz):**
- `POST /register_forms` - Register form/workflow from YAML
- `POST /runs` - Create workflow run with payload
- `POST /runs/{id}/advance` - Advance suspended run
- `GET /runs/{id}` - Get run status

## Dependencies Removed

From orchestrator-core's heavy dependency list:

### Removed:
- `celery` - Task queue (not needed for sync execution)
- `redis` - Celery backend (optional in future)
- `strawberry-graphql` - GraphQL API (not needed)
- `nwastdlib` - SURF-specific utilities (used `const`, `identity` - trivial to inline)
- `oauth2-lib` - OIDC integration (future addition)
- `pgvector` - Vector search (not needed)
- `more-itertools` - Utility library (kept minimal usage)
- `sqlalchemy-utils` - UUID/TSVector types (simplified to basic types)

### Kept:
- `pydantic` (v2) - Form validation
- `sqlalchemy` - Database ORM
- `fastapi` - API framework
- `structlog` - Structured logging
- `pyyaml` - YAML parsing

### Added:
- `pydantic-forms` - Form UI integration

## Architecture Simplification

### Old Architecture (Orchestrator-Core):
```
Product Definition (DB)
  ↓
Product Block Models (Python classes)
  ↓
Subscription Model (lifecycle-aware)
  ↓
Workflow (tied to product)
  ↓
Process Execution (Celery tasks)
  ↓
Subscription Instance (DB)
```

### New Architecture (Saz):
```
Form Definition (YAML)
  ↓
Pydantic Model (generated)
  ↓
Workflow (generic steps)
  ↓
Run Execution (sync)
  ↓
Run State (DB)
```

## What Was Kept and Why

### Workflow Engine Core:
- **Process ADT** - Core state management (Success/Failed/etc.)
- **Step abstractions** - Step/StepList/Workflow protocols
- **Execution logic** - `runwf()` and `_exec_steps()`

**Why:** This is the essential orchestration logic. It's domain-agnostic and powers the workflow execution.

### Database Models:
- **WorkflowTable** - Generic workflow definitions
- **Process/Step tables** - Renamed to Run/RunStep but conceptually same

**Why:** Workflow execution tracking is domain-agnostic.

## What Was Replaced

### Product/Subscription Models → Generic Forms:
- Old: Python classes with `ProductBlockModel`, `SubscriptionModel`
- New: YAML → Pydantic v2 dynamic models

**Why:** Generic forms don't need the complex lifecycle/hierarchy of products/subscriptions.

### GraphQL API → Simple REST:
- Old: Strawberry GraphQL with complex resolvers
- New: FastAPI with 4 endpoints

**Why:** GraphQL is overkill for simple form/workflow management.

### Celery Tasks → Synchronous Execution:
- Old: Workflows executed as async Celery tasks
- New: Workflows executed synchronously in API request

**Why:** Simplicity. Can add async later if needed.

## Consequences and Trade-offs

### Gains:
✅ **Simplicity** - 1000s of lines removed
✅ **Generic** - No domain coupling
✅ **Fast** - No Celery overhead
✅ **Easy to understand** - Clear data flow
✅ **Lightweight** - Fewer dependencies

### Losses:
❌ **Advanced features** - No retry, callback steps, conditionals (can add back)
❌ **Async execution** - No background tasks (can add Celery back if needed)
❌ **Complex hierarchies** - No product block trees (not needed for simple forms)
❌ **Lifecycle management** - No subscription lifecycle (not needed)
❌ **Multi-tenancy** - No customer isolation (can add)

## Migration Path (If Needed)

If you need orchestrator-core features in saz:

### 1. Add Celery Back:
```python
from celery import Celery
app = Celery('saz', broker='redis://localhost')

@app.task
def execute_workflow(run_id):
    # Execute workflow async
    pass
```

### 2. Add Conditional Steps:
```python
# In engine/workflow.py, restore conditional() function
```

### 3. Add Authentication:
```python
# Use fastapi-users or similar
from fastapi_users import FastAPIUsers
```

### 4. Add Retry Steps:
```python
# Restore retrystep() decorator from orchestrator-core
```

## Conclusion

Saz is a **minimal viable orchestration engine** that keeps the core workflow execution logic from orchestrator-core but removes all domain-specific concepts (products, subscriptions, etc.).

This makes it suitable as a **general-purpose forms and workflows engine** where users can define forms in YAML and get a working workflow system without needing to understand telecom provisioning concepts.

The vendored workflow engine is **~500 lines** vs orchestrator-core's **~45,000 lines**.
