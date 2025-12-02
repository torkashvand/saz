"""Clean FastAPI application with modular router structure.

This module provides a thin bootstrap layer that:
- Initializes the FastAPI app with lifespan management
- Configures middleware (CORS)
- Registers error handlers
- Includes domain-based routers from saz.api.routes.*
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from saz.api.errors import (
    ServiceError,
    generic_error_handler,
    service_error_handler,
    value_error_handler,
)
from saz.engine.scheduler import get_scheduler
from saz.globals import initialize_globals
from saz.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle management."""
    database_url = settings.DATABASE_URL

    # Initialize global singletons (planner, critic, policy engine, etc.)
    initialize_globals(
        planner_model=settings.PLANNER_MODEL,
        critic_model=settings.CRITIC_MODEL,
    )

    get_scheduler(database_url)

    yield

    # Shutdown scheduler gracefully
    try:
        scheduler = get_scheduler()
        scheduler.shutdown(wait=False)
    except Exception:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Saz Agentic Workflow Engine",
        version="2.0.0",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )

    # Register exception handlers
    app.add_exception_handler(ServiceError, service_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include domain-based routers
    from saz.api.routes.credentials import router as credentials_router
    from saz.api.routes.flows import router as flows_router
    from saz.api.routes.health import router as health_router
    from saz.api.routes.runs import router as runs_router
    from saz.api.routes.stream import router as stream_router
    from saz.api.routes.templates import router as templates_router
    from saz.api.routes.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(flows_router)
    app.include_router(runs_router)
    app.include_router(credentials_router)
    app.include_router(templates_router)
    app.include_router(webhooks_router)
    app.include_router(stream_router)

    return app


# Create application instance
app = create_app()
