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
