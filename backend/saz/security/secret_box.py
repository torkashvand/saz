"""Symmetric encryption for secrets stored at rest (e.g. OIDC client
secrets), reusing the same Fernet key as credential storage.

Kept separate from ``CredentialService`` so non-credential secrets can be
sealed without pulling in the credential aggregate.
"""

from cryptography.fernet import Fernet

from saz.settings import settings


def _cipher() -> Fernet:
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "CREDENTIALS_ENCRYPTION_KEY is not configured; cannot seal secrets at rest."
        )
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt a secret string for storage. Returns Fernet ciphertext bytes."""
    return _cipher().encrypt(plaintext.encode())


def decrypt_secret(token: bytes) -> str:
    """Decrypt ciphertext produced by :func:`encrypt_secret`."""
    return _cipher().decrypt(token).decode()
