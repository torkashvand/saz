"""add auth_providers.redirect_uri override for IdP-registered callback

Lets a provider override the redirect URI sent to the IdP (and used in the
token exchange) to match its registration; null uses the default callback.

Revision ID: 009
Revises: 008
Create Date: 2026-06-24

"""

import sqlalchemy as sa

from alembic import op

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'auth_providers',
        sa.Column('redirect_uri', sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('auth_providers', 'redirect_uri')
