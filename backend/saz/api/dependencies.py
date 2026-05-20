"""FastAPI dependency injection helpers for services."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from saz.db.dependencies import get_uow
from saz.db.models import User
from saz.db.unit_of_work import UnitOfWork
from saz.services.auth_service import AuthError, AuthService
from saz.services.credential_service import CredentialService
from saz.services.flow_service import FlowService
from saz.services.run_service import RunService


def get_flow_service(uow: UnitOfWork = Depends(get_uow)) -> FlowService:
    """Get FlowService instance with UnitOfWork."""
    return FlowService(uow)


def get_run_service(uow: UnitOfWork = Depends(get_uow)) -> RunService:
    """Get RunService instance with UnitOfWork."""
    return RunService(uow)


def get_credential_service(uow: UnitOfWork = Depends(get_uow)) -> CredentialService:
    """Get CredentialService instance with UnitOfWork."""
    return CredentialService(uow)


def get_auth_service(uow: UnitOfWork = Depends(get_uow)) -> AuthService:
    """Get AuthService instance with UnitOfWork."""
    return AuthService(uow)


# auto_error=False so the dependency yields None (not 403) when the header
# is missing — we want to translate every auth failure into 401 with our
# own envelope, including "no token provided".
_bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    """Require a valid bearer token and return the authenticated user.

    Raises HTTP 401 if the Authorization header is missing, malformed,
    expired, or refers to a deleted/disabled account.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("not authenticated")
    try:
        return auth.user_from_token(credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc


# Type aliases for cleaner endpoint signatures
FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_uow)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
