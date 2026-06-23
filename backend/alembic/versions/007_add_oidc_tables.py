"""add auth_providers and external_identities for OIDC SSO

Revision ID: 007
Revises: 006
Create Date: 2026-06-23

"""

import sqlalchemy as sa

from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_providers',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('provider_key', sa.String(length=64), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('issuer', sa.String(length=512), nullable=False),
        sa.Column('client_id', sa.String(length=512), nullable=False),
        sa.Column('client_secret_encrypted', sa.LargeBinary(), nullable=False),
        sa.Column(
            'scopes', sa.String(length=512), nullable=False, server_default='openid profile email'
        ),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('allowed_domains', sa.String(length=1024), nullable=True),
        sa.Column('jit_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('default_role', sa.String(length=20), nullable=False, server_default='viewer'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_auth_providers_provider_key', 'auth_providers', ['provider_key'], unique=True
    )

    op.create_table(
        'external_identities',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('provider_key', sa.String(length=64), nullable=False),
        sa.Column('issuer', sa.String(length=512), nullable=False),
        sa.Column('subject', sa.String(length=512), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('linked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('issuer', 'subject', name='uq_external_identity_subject'),
    )
    op.create_index('ix_external_identities_user_id', 'external_identities', ['user_id'])
    op.create_index('ix_external_identities_provider_key', 'external_identities', ['provider_key'])


def downgrade() -> None:
    op.drop_index('ix_external_identities_provider_key', table_name='external_identities')
    op.drop_index('ix_external_identities_user_id', table_name='external_identities')
    op.drop_table('external_identities')
    op.drop_index('ix_auth_providers_provider_key', table_name='auth_providers')
    op.drop_table('auth_providers')
