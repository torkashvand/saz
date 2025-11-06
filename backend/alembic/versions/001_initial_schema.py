"""Initial schema for clean architecture

Revision ID: 001_initial
Revises:
Create Date: 2025-01-12 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create flows table
    op.create_table(
        'flows',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('version', sa.String(50), nullable=True),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_flows_name', 'flows', ['name'])

    # Create runs table
    op.create_table(
        'runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'flow_id', sa.String(36), sa.ForeignKey('flows.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('error', sa.JSON(), nullable=True),
        sa.Column('cost_cents', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_runs_flow_id', 'runs', ['flow_id'])
    op.create_index('ix_runs_status', 'runs', ['status'])
    op.create_index('ix_runs_created_at', 'runs', ['created_at'])

    # Create steps table
    op.create_table(
        'steps',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'run_id', sa.String(36), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('start_ts', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_ts', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output', sa.JSON(), nullable=True),
        sa.Column('error', sa.JSON(), nullable=True),
    )
    op.create_index('ix_steps_run_id', 'steps', ['run_id'])

    # Create artifacts table
    op.create_table(
        'artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'run_id', sa.String(36), sa.ForeignKey('runs.id', ondelete='CASCADE'), nullable=False
        ),
        sa.Column(
            'step_id', sa.String(36), sa.ForeignKey('steps.id', ondelete='SET NULL'), nullable=True
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('blob_ref', sa.String(1000), nullable=False),
        sa.Column('meta', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_artifacts_run_id', 'artifacts', ['run_id'])
    op.create_index('ix_artifacts_step_id', 'artifacts', ['step_id'])

    # Create credentials table
    op.create_table(
        'credentials',
        sa.Column('name', sa.String(255), primary_key=True),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('description', sa.String(1000), nullable=True),
        sa.Column('data_encrypted', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Add agentic loop tracking fields to steps table
    op.add_column('steps', sa.Column('input', sa.JSON(), nullable=True))
    op.add_column('steps', sa.Column('tokens', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('steps', sa.Column('cost_usd', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('steps', sa.Column('critique', sa.JSON(), nullable=True))
    op.add_column('steps', sa.Column('policy_flags', sa.JSON(), nullable=True))
    op.add_column('steps', sa.Column('step_type', sa.String(50), nullable=True))

    # Add compliance tracking fields to runs table
    op.add_column(
        'runs', sa.Column('total_tokens', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column('runs', sa.Column('policy_violations', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_table('credentials')
    op.drop_table('artifacts')
    op.drop_table('steps')
    op.drop_table('runs')
    op.drop_table('flows')
