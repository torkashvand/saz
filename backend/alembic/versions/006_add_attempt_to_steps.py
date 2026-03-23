"""Add attempt column to steps table

Revision ID: 006
Revises: 005
Create Date: 2026-03-21 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add attempt column to distinguish multiple attempts of the same step within a run."""
    op.add_column('steps', sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Remove attempt column."""
    op.drop_column('steps', 'attempt')
