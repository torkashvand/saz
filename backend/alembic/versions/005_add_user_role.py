"""replace users.is_admin with a role tier

Revision ID: 005
Revises: 004
Create Date: 2026-06-23

``role`` becomes the single source of truth for a user's authorization tier.
``is_admin`` is retired as a column and lives on only as a derived property in
the ORM. Existing admins backfill to ``admin``; everyone else to ``operator``.
"""

import sqlalchemy as sa

from alembic import op

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column(
                'role',
                sa.String(length=20),
                nullable=False,
                server_default='operator',
            )
        )

    users = sa.table('users', sa.column('role', sa.String), sa.column('is_admin', sa.Boolean))
    op.execute(users.update().where(users.c.is_admin.is_(True)).values(role='admin'))

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('is_admin')

    op.create_index('ix_users_role', 'users', ['role'])


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_admin',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    users = sa.table('users', sa.column('role', sa.String), sa.column('is_admin', sa.Boolean))
    op.execute(users.update().where(users.c.role == 'admin').values(is_admin=True))

    op.drop_index('ix_users_role', table_name='users')

    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('role')
