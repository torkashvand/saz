"""Admin user-management service.

Wraps ``UserRepository`` with safety rails and audit. Authorization
itself is enforced one layer up (the ``get_current_admin`` FastAPI
dependency); this service trusts that the caller is already a
verified admin and focuses on the business rules:

* The last *active* admin cannot be disabled or demoted — there must
  always be at least one admin left who can recover the system.
* Admin password resets must flip ``must_change_password=True`` so the
  recipient is forced to pick a new password on next login.
* Plaintext passwords never enter the audit log.
"""

from saz.api.errors import ConflictError, ValidationError
from saz.audit.admin_audit import admin_audit
from saz.db.models import User
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.security import hash_password
from saz.services.auth_service import AuthService


class AdminError(Exception):
    """Raised when an admin operation violates a safety rail."""


class AdminService:
    """Service for admin-only user-management operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        # AuthService owns validation + creation logic; reuse it so the
        # admin API and the CLI go through the same code path.
        self._auth = AuthService(uow)

    # --- Reads ---

    def list_users(self, limit: int = 200, offset: int = 0) -> tuple[list[User], int]:
        assert self.uow.users is not None
        return self.uow.users.list_all(limit=limit, offset=offset)

    def get_user(self, user_id: str) -> User | None:
        assert self.uow.users is not None
        return self.uow.users.get(user_id)

    # --- Mutations (each commits + audits) ---

    def create_user(
        self,
        actor: User,
        username: str,
        email: str,
        password: str,
        display_name: str | None = None,
        role: Role = Role.OPERATOR,
        is_active: bool = True,
        must_change_password: bool = False,
    ) -> User:
        user = self._auth.create_user(
            username=username,
            email=email,
            password=password,
            display_name=display_name,
            role=role,
            is_active=is_active,
            must_change_password=must_change_password,
        )
        admin_audit(
            "user.created",
            actor_user_id=actor.id,
            actor_username=actor.username,
            target_user_id=user.id,
            target_username=user.username,
            changes={
                "email": user.email,
                "display_name": user.display_name,
                "role": user.role,
                "is_active": user.is_active,
                "must_change_password": user.must_change_password,
            },
        )
        return user

    def update_profile(
        self,
        actor: User,
        user_id: str,
        *,
        username: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
    ) -> User:
        """Update mutable profile fields.

        Username changes are audited but otherwise treated like any other
        field — the previous "immutable" rule was lifted at the admin's
        request. The audit event still records the old username on
        ``changes["username"]["from"]`` so attribution remains traceable
        for events emitted before the rename.
        """
        assert self.uow.users is not None
        user = self.uow.users.get(user_id)
        if user is None:
            raise AdminError(f"user not found: {user_id}")

        changes: dict[str, object] = {}
        if username is not None:
            new_username = AuthService._validate_username(username)
            if new_username != user.username:
                existing = self.uow.users.get_by_username(new_username)
                if existing is not None and existing.id != user.id:
                    raise ConflictError(f"username already taken: {new_username}")
                changes["username"] = {"from": user.username, "to": new_username}
                user.username = new_username
        if email is not None:
            new_email = AuthService._validate_email(email)
            if new_email != user.email:
                existing = self.uow.users.get_by_email(new_email)
                if existing is not None and existing.id != user.id:
                    raise ConflictError(f"email already registered: {new_email}")
                changes["email"] = {"from": user.email, "to": new_email}
                user.email = new_email
        if display_name is not None:
            new_name = display_name.strip() or None
            if new_name != user.display_name:
                changes["display_name"] = {
                    "from": user.display_name,
                    "to": new_name,
                }
                user.display_name = new_name

        if changes:
            self.uow.commit()
            admin_audit(
                "user.updated",
                actor_user_id=actor.id,
                actor_username=actor.username,
                target_user_id=user.id,
                target_username=user.username,
                changes=changes,
            )
        return user

    def set_active(self, actor: User, user_id: str, is_active: bool) -> User:
        assert self.uow.users is not None
        user = self.uow.users.get(user_id)
        if user is None:
            raise AdminError(f"user not found: {user_id}")

        if user.is_active == is_active:
            return user  # no-op, no event

        if not is_active:
            self._guard_last_admin(user)
            if actor.id == user.id:
                raise AdminError("admins cannot disable their own account")

        user.is_active = is_active
        self.uow.commit()
        admin_audit(
            "user.activated" if is_active else "user.disabled",
            actor_user_id=actor.id,
            actor_username=actor.username,
            target_user_id=user.id,
            target_username=user.username,
        )
        return user

    def set_role(self, actor: User, user_id: str, role: Role) -> User:
        assert self.uow.users is not None
        user = self.uow.users.get(user_id)
        if user is None:
            raise AdminError(f"user not found: {user_id}")

        if user.role == role:
            return user  # no-op, no event

        # Dropping the admin tier must not strand the system without an
        # admin, and an admin cannot demote themselves.
        if user.role == Role.ADMIN and role != Role.ADMIN:
            self._guard_last_admin(user)
            if actor.id == user.id:
                raise AdminError("admins cannot change their own role")

        previous = user.role
        user.role = role
        self.uow.commit()
        admin_audit(
            "user.role_changed",
            actor_user_id=actor.id,
            actor_username=actor.username,
            target_user_id=user.id,
            target_username=user.username,
            changes={"role": {"from": previous, "to": role}},
        )
        return user

    def reset_password(
        self,
        actor: User,
        user_id: str,
        temporary_password: str,
    ) -> User:
        """Admin sets a temporary password and forces the user to change
        it on next login. Plaintext is never logged.
        """
        assert self.uow.users is not None
        user = self.uow.users.get(user_id)
        if user is None:
            raise AdminError(f"user not found: {user_id}")

        if len(temporary_password) < 8:
            raise ValidationError("temporary password must be at least 8 characters")

        user.password_hash = hash_password(temporary_password)
        user.must_change_password = True
        self.uow.commit()
        admin_audit(
            "user.password_reset",
            actor_user_id=actor.id,
            actor_username=actor.username,
            target_user_id=user.id,
            target_username=user.username,
        )
        return user

    # --- Internal helpers ---

    def _guard_last_admin(self, target: User) -> None:
        """Block changes that would leave zero active admins."""
        if not (target.role == Role.ADMIN and target.is_active):
            return
        assert self.uow.users is not None
        active = self.uow.users.count_active_admins()
        if active <= 1:
            raise AdminError("refusing to disable or demote the last active admin")
