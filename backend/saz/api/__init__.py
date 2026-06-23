"""Clean FastAPI application with modular router structure.

This module provides a thin bootstrap layer that:
- Initializes the FastAPI app with lifespan management
- Configures middleware (CORS)
- Registers error handlers
- Includes domain-based routers from saz.api.routes.*
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from saz.api.errors import (
    ServiceError,
    generic_error_handler,
    service_error_handler,
    value_error_handler,
)
from saz.engine.scheduler import get_scheduler
from saz.engine.suspension_sweeper import get_suspension_sweeper
from saz.globals import initialize_globals
from saz.settings import settings

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle management."""
    # Fail loud on boot if the JWT secret is missing. Without it, every
    # login 500s — and because exception responses can lose CORS headers,
    # the browser surfaces it as a misleading "Connection issue" instead
    # of a server error. Crashing here puts the real cause in operator
    # logs the first time uvicorn comes up.
    if not settings.JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured. Generate one with "
            "`openssl rand -hex 32` and add it to backend/.env before "
            "starting the server."
        )

    database_url = settings.DATABASE_URL

    # Initialize global singletons (planner, critic, policy engine, etc.)
    initialize_globals(
        planner_model=settings.PLANNER_MODEL,
        critic_model=settings.CRITIC_MODEL,
    )

    get_scheduler(database_url)

    # Start the suspension sweeper so suspended runs whose deadline has
    # passed are reaped and transitioned to failed/SuspensionTimeout.
    if settings.SUSPENSION_SWEEP_ENABLED:
        sweeper = get_suspension_sweeper(
            database_url,
            interval_seconds=settings.SUSPENSION_SWEEP_INTERVAL_SECONDS,
            batch_limit=settings.SUSPENSION_SWEEP_BATCH_LIMIT,
        )
        sweeper.start()

    yield

    # Shutdown scheduler gracefully
    try:
        scheduler = get_scheduler()
        scheduler.shutdown(wait=False)
    except Exception as exc:
        logger.warning("scheduler_shutdown_failed", error=str(exc))
    if settings.SUSPENSION_SWEEP_ENABLED:
        try:
            get_suspension_sweeper().stop()
        except Exception as exc:
            logger.warning("suspension_sweeper_stop_failed", error=str(exc))


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

    # Configure CORS. The allow-list lives on settings so the middleware
    # and the exception-handler responses (which CORSMiddleware does not
    # always decorate) share one source of truth — otherwise a 500 ships
    # without Access-Control-Allow-Origin and the browser surfaces it as a
    # network failure.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include domain-based routers
    from saz.api.routes.admin import router as admin_router
    from saz.api.routes.admin_auth import router as admin_auth_router
    from saz.api.routes.auth import router as auth_router
    from saz.api.routes.credentials import router as credentials_router
    from saz.api.routes.flows import router as flows_router
    from saz.api.routes.health import router as health_router
    from saz.api.routes.oidc import router as oidc_router
    from saz.api.routes.runs import router as runs_router
    from saz.api.routes.stream import router as stream_router
    from saz.api.routes.templates import router as templates_router
    from saz.api.routes.webhooks import router as webhooks_router

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(oidc_router)
    app.include_router(admin_router)
    app.include_router(admin_auth_router)
    app.include_router(flows_router)
    app.include_router(runs_router)
    app.include_router(credentials_router)
    app.include_router(templates_router)
    app.include_router(webhooks_router)
    app.include_router(stream_router)

    return app
