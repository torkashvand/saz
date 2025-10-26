"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-11 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create flows table
    op.create_table(
        'flows',
        sa.Column('flow_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('definition', JSON, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Create runs table
    op.create_table(
        'runs',
        sa.Column('run_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('flow_id', UUID(as_uuid=True), sa.ForeignKey('flows.flow_id'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('current_state', JSON, nullable=False),
        sa.Column('created_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_runs_flow_id', 'runs', ['flow_id'])

    # Create run_steps table
    op.create_table(
        'run_steps',
        sa.Column('step_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('runs.run_id'), nullable=False),
        sa.Column('step_number', sa.Integer, nullable=False),
        sa.Column('step_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('state', JSON, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_run_steps_run_id', 'run_steps', ['run_id'])


def downgrade() -> None:
    op.drop_table('run_steps')
    op.drop_table('runs')
    op.drop_table('flows')
