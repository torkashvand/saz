"""Refresh-session secret generation and hashing.

The refresh secret is a high-entropy random string handed to the client in
an HttpOnly cookie. Only its SHA-256 hash is stored, so a database leak does
not expose usable refresh tokens. A fast hash is appropriate here (unlike
passwords) because the secret has full entropy and is not user-chosen.
"""

import hashlib
import secrets


def generate_refresh_secret() -> str:
    """Return a new URL-safe refresh secret (~64 chars, 48 bytes entropy)."""
    return secrets.token_urlsafe(48)


def hash_refresh_secret(secret: str) -> str:
    """Hash a refresh secret for storage/lookup. Returns 64 hex chars."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
