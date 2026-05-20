"""Structured audit logger for admin / user-management actions.

The DB ``events`` table is run-scoped (FK to ``runs.id`` NOT NULL), so
user-management audit lines live in structured logs instead. Production
deployments are expected to ship these to a SIEM or central log store.

Every line carries:
- ``audit``: "admin"          (constant tag for filtering)
- ``event_type``: stable name (user.created, user.disabled, ...)
- ``actor_user_id`` / ``actor_username``: the admin who acted
- ``target_user_id`` / ``target_username``: the user being acted on
- ``changes``: optional dict of what changed

Plaintext passwords, password hashes, and JWTs are never logged.
"""

from typing import Any

import structlog

_logger = structlog.get_logger("saz.audit.admin")


def admin_audit(
    event_type: str,
    *,
    actor_user_id: str,
    actor_username: str,
    target_user_id: str,
    target_username: str,
    changes: dict[str, Any] | None = None,
) -> None:
    """Emit one structured audit line for an admin user-management action.

    Caller is responsible for never passing secret material in ``changes``.
    The function silently drops any key whose value looks password-shaped
    as a defense-in-depth measure.
    """
    safe_changes = _strip_secrets(changes or {})
    _logger.info(
        "admin_audit",
        audit="admin",
        event_type=event_type,
        actor_user_id=actor_user_id,
        actor_username=actor_username,
        target_user_id=target_user_id,
        target_username=target_username,
        changes=safe_changes,
    )


_SECRET_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "password_hash",
        "token",
        "access_token",
        "jwt",
    }
)


def _strip_secrets(d: dict[str, Any]) -> dict[str, Any]:
    """Drop anything obviously secret-shaped before logging."""
    return {k: v for k, v in d.items() if k.lower() not in _SECRET_KEYS}
