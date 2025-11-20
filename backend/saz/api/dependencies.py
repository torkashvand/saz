"""FastAPI dependency injection helpers for services."""

from typing import Annotated

from fastapi import Depends

from saz.db.dependencies import get_uow
from saz.db.unit_of_work import UnitOfWork
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


# Type aliases for cleaner endpoint signatures
FlowServiceDep = Annotated[FlowService, Depends(get_flow_service)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
CredentialServiceDep = Annotated[CredentialService, Depends(get_credential_service)]
UnitOfWorkDep = Annotated[UnitOfWork, Depends(get_uow)]
