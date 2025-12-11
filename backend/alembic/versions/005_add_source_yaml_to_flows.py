"""Add source_yaml column to flows table

Revision ID: 005
Revises: 004
Create Date: 2025-01-12 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add source_yaml column to store original YAML DSL."""
    op.add_column('flows', sa.Column('source_yaml', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove source_yaml column."""
    op.drop_column('flows', 'source_yaml')
