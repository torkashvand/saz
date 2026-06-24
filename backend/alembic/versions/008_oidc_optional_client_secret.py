"""make auth_providers.client_secret_encrypted nullable for public clients

Public (PKCE-only) OIDC clients authenticate without a client secret.

Revision ID: 008
Revises: 007
Create Date: 2026-06-24

"""

import sqlalchemy as sa

from alembic import op

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('auth_providers') as batch:
        batch.alter_column(
            'client_secret_encrypted',
            existing_type=sa.LargeBinary(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('auth_providers') as batch:
        batch.alter_column(
            'client_secret_encrypted',
            existing_type=sa.LargeBinary(),
            nullable=False,
        )
