"""Global error envelope and exception handlers."""

from datetime import UTC, datetime

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Detailed error information."""

    field: str | None = None
    message: str
    code: str | None = None


class ErrorEnvelope(BaseModel):
    """Standardized error response envelope."""

    error: str
    message: str
    details: list[ErrorDetail] | None = None
    request_id: str | None = None
    timestamp: str


class ServiceError(Exception):
    """Base service error."""

    def __init__(self, message: str, code: str = "service_error", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(ServiceError):
    """Resource not found error."""

    def __init__(self, message: str):
        super().__init__(message, "not_found", 404)


class ValidationError(ServiceError):
    """Validation error."""

    def __init__(self, message: str):
        super().__init__(message, "validation_error", 400)


class ConflictError(ServiceError):
    """Conflict error."""

    def __init__(self, message: str):
        super().__init__(message, "conflict", 409)


async def service_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle service errors."""
    assert isinstance(exc, ServiceError)
    envelope = ErrorEnvelope(
        error=exc.code, message=exc.message, timestamp=datetime.now(UTC).isoformat()
    )
    # Include 'detail' for FastAPI compatibility
    response_data = envelope.model_dump()
    response_data["detail"] = exc.message
    return JSONResponse(status_code=exc.status_code, content=response_data)


async def value_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle value errors as validation errors."""
    assert isinstance(exc, ValueError)
    envelope = ErrorEnvelope(
        error="validation_error", message=str(exc), timestamp=datetime.now(UTC).isoformat()
    )
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=envelope.model_dump())


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors."""
    envelope = ErrorEnvelope(
        error="internal_error",
        message="An unexpected error occurred",
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump()
    )
