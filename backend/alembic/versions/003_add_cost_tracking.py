"""add cost tracking to runs and run_steps

Revision ID: 003
Revises: bc44c45eaa35
Create Date: 2025-10-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '003'
down_revision = 'bc44c45eaa35'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add cost tracking columns to runs table
    op.add_column('runs', sa.Column('tokens_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('runs', sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0.0'))

    # Add cost tracking columns to run_steps table
    op.add_column('run_steps', sa.Column('tokens', sa.Integer(), nullable=True))
    op.add_column('run_steps', sa.Column('cost_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    # Remove cost tracking columns from run_steps
    op.drop_column('run_steps', 'cost_usd')
    op.drop_column('run_steps', 'tokens')

    # Remove cost tracking columns from runs
    op.drop_column('runs', 'cost_usd')
    op.drop_column('runs', 'tokens_used')
