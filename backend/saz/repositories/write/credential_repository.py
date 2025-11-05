"""Credential write repository."""
from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from saz.db.models import Credential
from saz.repositories.base import BaseRepository


class CredentialRepository:
    """Write repository for Credential aggregate."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(
        self,
        name: str,
        credential_type: str,
        data_encrypted: bytes,
        description: Optional[str] = None
    ) -> Credential:
        """Create or update credential."""
        stmt = select(Credential).where(Credential.name == name)
        credential = self.session.scalar(stmt)

        if credential:
            # Update existing
            credential.type = credential_type
            credential.data_encrypted = data_encrypted
            if description is not None:
                credential.description = description
            credential.updated_at = datetime.now(UTC)
        else:
            # Create new
            credential = Credential(
                name=name,
                type=credential_type,
                description=description,
                data_encrypted=data_encrypted,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
            self.session.add(credential)

        return credential

    def get(self, name: str) -> Optional[Credential]:
        """Get credential by name."""
        stmt = select(Credential).where(Credential.name == name)
        return self.session.scalar(stmt)

    def delete(self, name: str) -> bool:
        """Delete credential by name."""
        credential = self.get(name)
        if credential:
            self.session.delete(credential)
            return True
        return False