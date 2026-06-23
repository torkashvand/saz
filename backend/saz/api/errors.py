"""Global error envelope and exception handlers."""

from datetime import UTC, datetime

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from saz.settings import settings


def _cors_headers(request: Request) -> dict[str, str]:
    """Echo the request Origin back as CORS headers when it's allow-listed.

    FastAPI's CORSMiddleware applies to normal responses but not always to
    responses produced by ``add_exception_handler`` — those can ship without
    ``Access-Control-Allow-Origin``, which the browser then surfaces as a
    network failure. Setting the headers here makes error responses
    indistinguishable to the browser from successful ones.

    The allow-list lives on ``settings.ALLOWED_ORIGINS`` so the CORS
    middleware and these handlers cannot drift.
    """
    origin = request.headers.get("origin")
    if origin and origin in settings.ALLOWED_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
        }
    return {}


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


class AuthorizationError(ServiceError):
    """Authenticated but not permitted to access or act on this resource."""

    def __init__(self, message: str = "Not authorized to access this resource"):
        super().__init__(message, "forbidden", 403)


class FlowLintError(ServiceError):
    """Flow failed consistency linting; carries structured findings (422)."""

    def __init__(self, message: str, findings: list[dict], llm_ran: bool):
        super().__init__(message, "flow_lint_error", 422)
        self.findings = findings
        self.llm_ran = llm_ran


async def service_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle service errors."""
    assert isinstance(exc, ServiceError)
    envelope = ErrorEnvelope(
        error=exc.code, message=exc.message, timestamp=datetime.now(UTC).isoformat()
    )
    # Include 'detail' for FastAPI compatibility
    response_data = envelope.model_dump()
    response_data["detail"] = exc.message
    # FlowLintError carries structured findings for the builder/API consumers.
    findings = getattr(exc, "findings", None)
    if findings is not None:
        response_data["findings"] = findings
        response_data["llm_ran"] = getattr(exc, "llm_ran", False)
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data,
        headers=_cors_headers(request),
    )


async def value_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle value errors as validation errors."""
    assert isinstance(exc, ValueError)
    envelope = ErrorEnvelope(
        error="validation_error", message=str(exc), timestamp=datetime.now(UTC).isoformat()
    )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=envelope.model_dump(),
        headers=_cors_headers(request),
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors."""
    envelope = ErrorEnvelope(
        error="internal_error",
        message="An unexpected error occurred",
        timestamp=datetime.now(UTC).isoformat(),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope.model_dump(),
        headers=_cors_headers(request),
    )
