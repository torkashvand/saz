"""add_credentials_and_enhanced_step_tracking

Revision ID: bc44c45eaa35
Revises: 001
Create Date: 2025-10-26 09:55:15.743341

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON


revision = 'bc44c45eaa35'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create credentials table
    op.create_table(
        'credentials',
        sa.Column('credential_id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('encrypted_data', sa.LargeBinary, nullable=False),
        sa.Column('credential_type', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Add updated_at to flows table
    op.add_column('flows', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # Replace state column with structured fields in run_steps table
    op.drop_column('run_steps', 'state')
    op.add_column('run_steps', sa.Column('input_data', JSON, nullable=True))
    op.add_column('run_steps', sa.Column('output_data', JSON, nullable=True))
    op.add_column('run_steps', sa.Column('error', sa.Text, nullable=True))
    op.add_column('run_steps', sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'))
    op.add_column('run_steps', sa.Column('artifacts', JSON, nullable=True))


def downgrade() -> None:
    # Remove columns from run_steps and restore state
    op.drop_column('run_steps', 'artifacts')
    op.drop_column('run_steps', 'retry_count')
    op.drop_column('run_steps', 'error')
    op.drop_column('run_steps', 'output_data')
    op.drop_column('run_steps', 'input_data')
    op.add_column('run_steps', sa.Column('state', JSON, nullable=False, server_default='{}'))

    # Remove updated_at from flows
    op.drop_column('flows', 'updated_at')

    # Drop credentials table
    op.drop_table('credentials')
