"""Add UX enhancement fields to runs table.

Revision ID: 003
Revises: 002
Create Date: 2025-11-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: str | None = '002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add UX enhancement fields to runs table."""
    # Add started_at timestamp (when run actually started execution, may differ from created_at)
    op.add_column('runs', sa.Column('started_at', sa.DateTime(timezone=True), nullable=True))

    # Add error_summary JSON field for human-readable error information
    op.add_column('runs', sa.Column('error_summary', sa.JSON(), nullable=True))

    # Add run_metadata JSON field for aggregated step counts (note: 'metadata' is reserved in SQLAlchemy)
    op.add_column('runs', sa.Column('run_metadata', sa.JSON(), nullable=True))

    # Add triggered_by JSON field to track who/what started the run
    op.add_column('runs', sa.Column('triggered_by', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove UX enhancement fields from runs table."""
    op.drop_column('runs', 'triggered_by')
    op.drop_column('runs', 'run_metadata')
    op.drop_column('runs', 'error_summary')
    op.drop_column('runs', 'started_at')
