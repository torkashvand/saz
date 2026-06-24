"""add auth_providers.trust_email_verified for IdPs lacking email_verified

Some trusted IdPs (e.g. GEANT/eduGAIN) release email via UserInfo but never
set email_verified; this opt-in flag treats that email as verified.

Revision ID: 010
Revises: 009
Create Date: 2026-06-24

"""

import sqlalchemy as sa

from alembic import op

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'auth_providers',
        sa.Column(
            'trust_email_verified',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('auth_providers', 'trust_email_verified')
