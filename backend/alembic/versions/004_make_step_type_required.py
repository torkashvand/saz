"""Make step_type required

Revision ID: 004
Revises: 003
Create Date: 2025-01-21

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.alter_column('step_type', existing_type=sa.String(length=50), nullable=False)


def downgrade():
    with op.batch_alter_table('steps', schema=None) as batch_op:
        batch_op.alter_column('step_type', existing_type=sa.String(length=50), nullable=True)
