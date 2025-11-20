"""Health check and system status endpoints."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": "Saz Agentic Workflow Engine",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
    }


@router.get("/health")
async def health_check(
    uow: UnitOfWork = Depends(get_uow),
) -> JSONResponse:
    """Health check endpoint - verifies database connectivity."""
    try:
        # Simple database ping
        uow.execute("SELECT 1")

        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "database": "connected",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            },
        )
