"""Bootstrap script: create a user account from the command line.

Use this to seed the first user on a fresh deployment. It is the
recommended path until invitation flows exist, because the open
``POST /api/v1/auth/register`` endpoint should be disabled in production
once you have alternative ways to onboard users.

Usage:
    uv run python -m saz.scripts.create_user \\
        --username alice --email alice@example.com
    # password is read interactively (or via --password for scripting)
"""

import argparse
import getpass
import sys

from saz.db.session import SessionLocal
from saz.db.unit_of_work import UnitOfWork
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
    parser = argparse.ArgumentParser(description="Create a Saz user account.")
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
    args = parser.parse_args(argv)

    password = _read_password(args.password)

    session = SessionLocal()
    try:
        with UnitOfWork(session) as uow:
            auth = AuthService(uow)
            user = auth.register_user(
                username=args.username,
                email=args.email,
                password=password,
                display_name=args.display_name,
            )
        print(f"created user {user.username} ({user.id})")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
