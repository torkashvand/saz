"""Create events table for unified audit log

Revision ID: 002
Revises: 001
Create Date: 2025-11-20

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add planner_mode to runs table (needed for event context)
    op.add_column(
        'runs',
        sa.Column('planner_mode', sa.String(20), nullable=False, server_default='deterministic'),
    )

    # Add duration_ms to runs table (for performance tracking)
    op.add_column('runs', sa.Column('duration_ms', sa.Integer(), nullable=True))

    # Add total_cost_usd to runs table (replacing cost_cents)
    op.add_column(
        'runs', sa.Column('total_cost_usd', sa.Float(), nullable=False, server_default='0.0')
    )

    # Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('step_id', sa.String(36), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=True),
        sa.Column('planner_mode', sa.String(20), nullable=False),
        sa.Column('severity', sa.String(10), nullable=False, server_default='info'),
        sa.Column('actor', sa.String(10), nullable=False, server_default='system'),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('tags', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['step_id'], ['steps.id'], ondelete='CASCADE'),
    )

    # Create indexes for common query patterns
    op.create_index('ix_events_event_type', 'events', ['event_type'])
    op.create_index('ix_events_timestamp', 'events', ['timestamp'])
    op.create_index('ix_events_run_id', 'events', ['run_id'])
    op.create_index('ix_events_step_id', 'events', ['step_id'])
    op.create_index('ix_events_correlation_id', 'events', ['correlation_id'])
    op.create_index('ix_events_severity', 'events', ['severity', 'timestamp'])

    # Composite indexes for common queries
    op.create_index('ix_events_run_timestamp', 'events', ['run_id', 'timestamp'])
    op.create_index('ix_events_run_type', 'events', ['run_id', 'event_type'])
    op.create_index('ix_events_type_timestamp', 'events', ['event_type', 'timestamp'])

    # GIN index for JSONB tag queries
    op.create_index('ix_events_tags', 'events', ['tags'], postgresql_using='gin')


def downgrade() -> None:
    op.drop_table('events')
    op.drop_column('runs', 'total_cost_usd')
    op.drop_column('runs', 'duration_ms')
    op.drop_column('runs', 'planner_mode')
