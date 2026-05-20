"""add users table and user-attribution columns

Revision ID: 002
Revises: 001
Create Date: 2026-05-20

"""

import sqlalchemy as sa

from alembic import op

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Domain-owned tables now require an authenticated creator. Flow, Run, and
    # Credential rows cannot exist without one — system-scheduled runs will
    # acquire a service-user identity when that feature lands.
    with op.batch_alter_table('flows') as batch_op:
        batch_op.add_column(sa.Column('created_by_user_id', sa.String(length=36), nullable=False))
        batch_op.create_index(
            op.f('ix_flows_created_by_user_id'), ['created_by_user_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_flows_created_by_user_id_users',
            'users',
            ['created_by_user_id'],
            ['id'],
            ondelete='RESTRICT',
        )

    with op.batch_alter_table('runs') as batch_op:
        batch_op.add_column(sa.Column('created_by_user_id', sa.String(length=36), nullable=False))
        batch_op.create_index(
            op.f('ix_runs_created_by_user_id'), ['created_by_user_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_runs_created_by_user_id_users',
            'users',
            ['created_by_user_id'],
            ['id'],
            ondelete='RESTRICT',
        )

    with op.batch_alter_table('credentials') as batch_op:
        batch_op.add_column(sa.Column('created_by_user_id', sa.String(length=36), nullable=False))
        batch_op.create_index(
            op.f('ix_credentials_created_by_user_id'), ['created_by_user_id'], unique=False
        )
        batch_op.create_foreign_key(
            'fk_credentials_created_by_user_id_users',
            'users',
            ['created_by_user_id'],
            ['id'],
            ondelete='RESTRICT',
        )

    # Events keep actor_user_id nullable: system/LLM-emitted events have no
    # human owner by definition.
    with op.batch_alter_table('events') as batch_op:
        batch_op.add_column(sa.Column('actor_user_id', sa.String(length=36), nullable=True))
        batch_op.create_index(op.f('ix_events_actor_user_id'), ['actor_user_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_events_actor_user_id_users',
            'users',
            ['actor_user_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_constraint('fk_events_actor_user_id_users', type_='foreignkey')
        batch_op.drop_index(op.f('ix_events_actor_user_id'))
        batch_op.drop_column('actor_user_id')

    with op.batch_alter_table('credentials') as batch_op:
        batch_op.drop_constraint('fk_credentials_created_by_user_id_users', type_='foreignkey')
        batch_op.drop_index(op.f('ix_credentials_created_by_user_id'))
        batch_op.drop_column('created_by_user_id')

    with op.batch_alter_table('runs') as batch_op:
        batch_op.drop_constraint('fk_runs_created_by_user_id_users', type_='foreignkey')
        batch_op.drop_index(op.f('ix_runs_created_by_user_id'))
        batch_op.drop_column('created_by_user_id')

    with op.batch_alter_table('flows') as batch_op:
        batch_op.drop_constraint('fk_flows_created_by_user_id_users', type_='foreignkey')
        batch_op.drop_index(op.f('ix_flows_created_by_user_id'))
        batch_op.drop_column('created_by_user_id')

    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
