"""Credential service - business logic for credential operations."""

import yaml
from cryptography.fernet import Fernet
from sqlalchemy import select

from saz.db.models import Credential
from saz.db.unit_of_work import UnitOfWork
from saz.repositories.read.dtos import CredentialListItemDTO
from saz.settings import settings


class CredentialService:
    """Service for credential operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        # Get encryption key from environment
        key = settings.CREDENTIALS_ENCRYPTION_KEY
        self.cipher = Fernet(key.encode())

    def create(
        self,
        name: str,
        credential_type: str,
        data: dict,
        created_by_user_id: str,
        description: str | None = None,
    ) -> str:
        """Create or update credential."""
        assert self.uow.credentials is not None

        # Encrypt data
        data_yaml = yaml.dump(data)
        encrypted = self.cipher.encrypt(data_yaml.encode())

        # Upsert credential
        self.uow.credentials.upsert(
            name=name,
            credential_type=credential_type,
            data_encrypted=encrypted,
            created_by_user_id=created_by_user_id,
            description=description,
        )
        self.uow.commit()

        return name

    def get(self, name: str) -> dict | None:
        """Get decrypted credential data."""
        assert self.uow.credentials is not None
        credential = self.uow.credentials.get(name)
        if not credential:
            return None

        # Decrypt
        decrypted = self.cipher.decrypt(credential.data_encrypted)
        data = yaml.safe_load(decrypted.decode())

        return {
            "name": credential.name,
            "type": credential.type,
            "description": credential.description,
            "data": data,
            "created_at": credential.created_at.isoformat(),
            "updated_at": credential.updated_at.isoformat(),
        }

    def list(self) -> list[CredentialListItemDTO]:
        """List credentials (metadata only, no secrets)."""
        # Query credentials directly
        stmt = select(Credential).order_by(Credential.created_at.desc())
        credentials = self.uow._session.scalars(stmt).all()

        return [
            CredentialListItemDTO(
                name=c.name,
                type=c.type,
                description=c.description,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in credentials
        ]

    def update(self, name: str, data: dict, description: str | None = None) -> str:
        """Update credential.

        Updates only touch the secret payload and description; the original
        ``created_by_user_id`` is preserved on the existing row.
        """
        assert self.uow.credentials is not None

        existing = self.uow.credentials.get(name)
        if not existing:
            raise ValueError(f"Credential not found: {name}")

        data_yaml = yaml.dump(data)
        encrypted = self.cipher.encrypt(data_yaml.encode())

        self.uow.credentials.upsert(
            name=name,
            credential_type=existing.type,
            data_encrypted=encrypted,
            created_by_user_id=existing.created_by_user_id,
            description=description,
        )
        self.uow.commit()

        return name

    def delete(self, name: str) -> bool:
        """Delete credential."""
        assert self.uow.credentials is not None
        result = self.uow.credentials.delete(name)
        if result:
            self.uow.commit()
        return result
