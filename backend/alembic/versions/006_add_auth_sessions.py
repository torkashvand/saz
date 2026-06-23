"""add auth_sessions table for server-side refresh sessions

Revision ID: 006
Revises: 005
Create Date: 2026-06-23

"""

import sqlalchemy as sa

from alembic import op

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('refresh_secret_hash', sa.String(length=64), nullable=False),
        sa.Column('previous_refresh_secret_hash', sa.String(length=64), nullable=True),
        sa.Column('auth_method', sa.String(length=20), nullable=False, server_default='local'),
        sa.Column('provider_key', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('idle_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('absolute_expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(length=64), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_index(
        'ix_auth_sessions_refresh_secret_hash', 'auth_sessions', ['refresh_secret_hash']
    )


def downgrade() -> None:
    op.drop_index('ix_auth_sessions_refresh_secret_hash', table_name='auth_sessions')
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')
