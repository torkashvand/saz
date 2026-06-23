"""Bootstrap script: create the first admin user from the command line.

Use this to seed the very first admin on a fresh deployment. After
that admin exists, all further user creation happens through the
authenticated admin user-management API (``POST /api/v1/admin/users``).

There is no public registration and no forgot-password flow. The CLI is
the *only* way to mint an admin without already having admin
credentials.

Usage:
    uv run python -m saz.scripts.create_user \\
        --username alice --email alice@example.com
    # password is prompted interactively; pass --password for scripting.

    # Create a non-admin user (rarely useful outside tests — admins
    # should manage users through the API).
    uv run python -m saz.scripts.create_user \\
        --username bob --email bob@example.com --no-admin
"""

import argparse
import getpass
import sys

from saz.db.session import SessionLocal
from saz.db.unit_of_work import UnitOfWork
from saz.domain.literals import Role
from saz.services.auth_service import AuthService


def _read_password(provided: str | None) -> str:
    if provided:
        return provided
    pw = getpass.getpass("password: ")
    confirm = getpass.getpass("confirm:  ")
    if pw != confirm:
        print("error: passwords do not match", file=sys.stderr)
        sys.exit(2)
    return pw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a Saz user account (admin by default).",
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--display-name",
        default=None,
        help="Optional human-friendly name shown in the UI.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Plaintext password. Omit to read from a TTY prompt.",
    )
    admin_group = parser.add_mutually_exclusive_group()
    admin_group.add_argument(
        "--admin",
        dest="admin",
        action="store_true",
        help="Create an admin user (default).",
    )
    admin_group.add_argument(
        "--no-admin",
        dest="admin",
        action="store_false",
        help="Create a non-admin user. Not the recommended path — "
        "non-admin users should be created via the admin API.",
    )
    parser.set_defaults(admin=True)
    args = parser.parse_args(argv)

    password = _read_password(args.password)

    session = SessionLocal()
    try:
        with UnitOfWork(session) as uow:
            auth = AuthService(uow)
            user = auth.create_user(
                username=args.username,
                email=args.email,
                password=password,
                display_name=args.display_name,
                role=Role.ADMIN if args.admin else Role.OPERATOR,
                must_change_password=False,
            )
        flag = "admin" if user.is_admin else "user"
        print(f"created {flag} {user.username} ({user.id})")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
