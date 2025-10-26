"""Credentials vault - encrypted secret storage.

Uses Fernet (symmetric encryption) with key from environment.
Secrets are encrypted at rest in the database.
"""
import os
import json
from typing import Dict, Any, Optional
from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
import structlog

from .models import CredentialTable

logger = structlog.get_logger(__name__)


class CredentialsVault:
    """Manage encrypted credentials."""

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize vault with encryption key.

        Args:
            encryption_key: Base64-encoded Fernet key (from env if not provided)
        """
        # Get key from env or generate one (not recommended for prod)
        key_str = encryption_key or os.getenv("CREDENTIALS_ENCRYPTION_KEY")
        if not key_str:
            logger.warning("No CREDENTIALS_ENCRYPTION_KEY set, generating temporary key")
            key_str = Fernet.generate_key().decode()

        self.cipher = Fernet(key_str.encode() if isinstance(key_str, str) else key_str)
        self.logger = logger.bind(component="credentials_vault")

    def create_credential(
        self,
        db: Session,
        name: str,
        credential_type: str,
        data: Dict[str, Any],
        description: Optional[str] = None
    ) -> CredentialTable:
        """
        Create encrypted credential.

        Args:
            db: Database session
            name: Credential name (unique)
            credential_type: Type (ssh_key, api_token, password, etc.)
            data: Credential data to encrypt
            description: Optional description

        Returns:
            Created CredentialTable instance
        """
        # Encrypt data
        data_json = json.dumps(data)
        encrypted_data = self.cipher.encrypt(data_json.encode())

        # Store in database
        credential = CredentialTable(
            name=name,
            description=description,
            encrypted_data=encrypted_data,
            credential_type=credential_type
        )
        db.add(credential)
        db.commit()
        db.refresh(credential)

        self.logger.info("credential_created", name=name, type=credential_type)
        return credential

    def get_credential(
        self,
        db: Session,
        name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve and decrypt credential by name.

        Args:
            db: Database session
            name: Credential name

        Returns:
            Decrypted credential data or None if not found
        """
        credential = db.query(CredentialTable).filter(CredentialTable.name == name).first()
        if not credential:
            return None

        # Decrypt
        try:
            decrypted_data = self.cipher.decrypt(credential.encrypted_data)
            data = json.loads(decrypted_data.decode())
            return data
        except Exception as e:
            self.logger.error("credential_decryption_failed", name=name, error=str(e))
            return None

    def list_credentials(
        self,
        db: Session
    ) -> list[Dict[str, Any]]:
        """
        List all credentials (metadata only, no secrets).

        Args:
            db: Database session

        Returns:
            List of credential metadata dicts
        """
        credentials = db.query(CredentialTable).all()
        return [
            {
                "credential_id": str(cred.credential_id),
                "name": cred.name,
                "description": cred.description,
                "credential_type": cred.credential_type,
                "created_at": cred.created_at.isoformat(),
                "updated_at": cred.updated_at.isoformat()
            }
            for cred in credentials
        ]

    def delete_credential(
        self,
        db: Session,
        name: str
    ) -> bool:
        """
        Delete credential by name.

        Args:
            db: Database session
            name: Credential name

        Returns:
            True if deleted, False if not found
        """
        credential = db.query(CredentialTable).filter(CredentialTable.name == name).first()
        if not credential:
            return False

        db.delete(credential)
        db.commit()

        self.logger.info("credential_deleted", name=name)
        return True

    def update_credential(
        self,
        db: Session,
        name: str,
        data: Dict[str, Any],
        description: Optional[str] = None
    ) -> bool:
        """
        Update credential data.

        Args:
            db: Database session
            name: Credential name
            data: New credential data
            description: New description (optional)

        Returns:
            True if updated, False if not found
        """
        credential = db.query(CredentialTable).filter(CredentialTable.name == name).first()
        if not credential:
            return False

        # Encrypt new data
        data_json = json.dumps(data)
        encrypted_data = self.cipher.encrypt(data_json.encode())

        # Update
        credential.encrypted_data = encrypted_data
        if description is not None:
            credential.description = description

        db.commit()

        self.logger.info("credential_updated", name=name)
        return True


# Global vault instance (initialized on first import)
_vault_instance = None


def get_vault() -> CredentialsVault:
    """Get global credentials vault instance."""
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = CredentialsVault()
    return _vault_instance
