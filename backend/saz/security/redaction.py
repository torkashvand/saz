"""Value-based redaction of resolved secrets from persisted/returned data.

Secrets resolved via ``$secret(...)`` are baked into grounded tool arguments
for execution, but must never be persisted in ``step.input``/``step.output``,
returned by the API, or emitted in audit events. This module scrubs known
secret *values* (and any string that contains one as a substring) from
arbitrary JSON-like structures.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

REDACTED = "***REDACTED***"

# Secrets shorter than this are not substring-redacted to avoid scrubbing
# incidental short tokens (e.g. a value of "1") out of unrelated text.
_MIN_SECRET_LEN = 4

# Segment words that mark a dict key as carrying a credential/secret value.
# Matching is segment-aware (the key is split on non-alphanumerics), so
# "secret" covers client_secret / aws_secret_access_key, "token" covers
# auth_token / access_token / refresh_token, and "password" covers db_password —
# while plural/count keys like "tokens" / "total_tokens" / "max_tokens" are NOT
# flagged (they are usage metrics, not secrets).
_SENSITIVE_SEGMENTS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "secret",
        "secrets",
        "token",
        "apikey",
        "credential",
        "credentials",
        "authorization",
        "cookie",
    }
)

# A "key" segment is only sensitive when paired with one of these qualifiers,
# so api_key / private_key / encryption_key / signing_key match, but harmless
# identifiers like idempotency_key / cache_key / public_key do not.
_KEY_QUALIFIERS: frozenset[str] = frozenset(
    {"api", "private", "secret", "access", "encryption", "signing", "ssh", "gpg", "pgp", "auth"}
)


def is_sensitive_key(key: str) -> bool:
    """Return True if a dict key name suggests its value is a credential.

    Segment-aware: ``X-API-Key``, ``aws_secret_access_key``, ``client_secret``,
    ``auth_token``, and ``db_password`` all match, while count/metric keys like
    ``tokens``/``total_tokens``/``max_tokens`` and harmless identifiers like
    ``idempotency_key``/``cache_key`` do not.
    """
    normalised = key.lower().replace("-", "_")
    segments = [s for s in normalised.split("_") if s]
    seg_set = set(segments)
    if seg_set & _SENSITIVE_SEGMENTS:
        return True
    # Compact forms with no separators, e.g. "apikey", "authtoken".
    if "apikey" in normalised:
        return True
    # "key" only counts as sensitive next to a credential qualifier.
    if "key" in seg_set and (seg_set & _KEY_QUALIFIERS):
        return True
    return False


def redact_sensitive(obj: Any, secret_values: Iterable[str] = ()) -> Any:
    """Return a deep copy of ``obj`` safe to log, persist, or send to an LLM.

    Two layers are applied recursively:
      1. Any dict value whose key name looks sensitive (:func:`is_sensitive_key`)
         is replaced wholesale with :data:`REDACTED`.
      2. Any remaining string containing a known resolved secret value has that
         substring scrubbed.

    Structure is preserved so a verifier/critic can still reason about which
    fields are present without seeing their secret contents.
    """
    values = [s for s in secret_values if isinstance(s, str) and len(s) >= _MIN_SECRET_LEN]
    values.sort(key=len, reverse=True)
    return _redact(obj, values)


def _redact(obj: Any, values: list[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and is_sensitive_key(k):
                out[k] = REDACTED
            else:
                out[k] = _redact(v, values)
        return out
    if isinstance(obj, list):
        return [_redact(item, values) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(item, values) for item in obj)
    if isinstance(obj, str):
        return _scrub(obj, values) if values else obj
    return obj


def redact_secret_values(obj: Any, secret_values: Iterable[str]) -> Any:
    """Return a deep copy of ``obj`` with every known secret value scrubbed.

    Any string equal to or containing a secret value is replaced (the
    substring is swapped for ``REDACTED``). Dicts and lists are walked
    recursively; other types are returned unchanged.
    """
    values = [s for s in secret_values if isinstance(s, str) and len(s) >= _MIN_SECRET_LEN]
    if not values:
        return obj
    # Longest first so overlapping secrets redact fully.
    values.sort(key=len, reverse=True)
    return _scrub(obj, values)


def _scrub(obj: Any, values: list[str]) -> Any:
    if isinstance(obj, str):
        scrubbed = obj
        for secret in values:
            if secret in scrubbed:
                scrubbed = scrubbed.replace(secret, REDACTED)
        return scrubbed
    if isinstance(obj, dict):
        return {k: _scrub(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(item, values) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_scrub(item, values) for item in obj)
    return obj
