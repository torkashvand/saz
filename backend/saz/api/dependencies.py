"""FastAPI dependency injection helpers for services and auth.

Auth gating is split into three layers so /auth/me and
/auth/change_password stay reachable for users in the
``must_change_password`` state:

* ``get_authenticated_user`` — valid JWT + active account; password may
  still be in the must-change state. Use for endpoints the user must be
  able to reach even before they have picked a new password.
* ``get_current_user`` — adds the must-change check. Use for read
  endpoints any authenticated tier may reach. ``CurrentUserDep`` is
  wired to this.
* ``get_operator_user`` — adds the write-access check (admin or
  operator, i.e. not a viewer). Use for mutating endpoints.
  ``OperatorUserDep`` is wired to this.
* ``get_current_admin`` — adds the admin check. Use for /admin/*.

Authorization is a single ``role`` tier (admin / operator / viewer);
there is no per-permission framework, which is enough for a self-hosted
product.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from saz.db.dependencies import get_uow
from saz.db.models import User
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.services.admin_service import AdminService
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


def get_admin_service(uow: UnitOfWork = Depends(get_uow)) -> AdminService:
    """Get AdminService instance with UnitOfWork."""
    return AdminService(uow)


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


def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> User:
    """Decode the bearer token and return the live user row.

    Returns the user even if ``must_change_password`` is True — operational
    endpoints opt into that stricter check via ``get_current_user``. This
    looser variant exists so /auth/me and /auth/change_password keep
    working for users in the forced-change state.

    Raises HTTP 401 if the Authorization header is missing, malformed,
    expired, or refers to a deleted/disabled account.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("not authenticated")
    try:
        return auth.user_from_token(credentials.credentials)
    except AuthError as exc:
        raise _unauthorized(str(exc)) from exc


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    """Authenticated + active + has picked their own password.

    Use this for every operational endpoint. Users in the forced
    must-change state are turned away with HTTP 403 and a specific code
    so the frontend can redirect them to the change-password screen.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="password change required",
            headers={"X-Password-Change-Required": "true"},
        )
    return user


def get_operator_user(user: User = Depends(get_current_user)) -> User:
    """Require write access: an admin or operator, never a viewer.

    Viewers are read-only — they reach GET endpoints through
    ``get_current_user`` but are turned away from any mutating endpoint
    with HTTP 403. The security boundary is here, not in the UI.
    """
    if user.role == Role.VIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="write access required",
        )
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Require an authenticated admin user.

    Builds on top of ``get_current_user`` so admins also can't reach the
    admin panel while in the forced password-change state.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access required",
        )
    return user


# Type aliases for cleaner endpoint signatures
FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
AdminServiceDep = Annotated[AdminService, Depends(get_admin_service)]
UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_uow)]
AuthenticatedUserDep = Annotated[User, Depends(get_authenticated_user)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
OperatorUserDep = Annotated[User, Depends(get_operator_user)]
AdminUserDep = Annotated[User, Depends(get_current_admin)]
