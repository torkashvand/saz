"""add monotonic per-run seq column to events

Revision ID: 004
Revises: 003
Create Date: 2026-06-02

The seq column gives the event stream a deterministic, gap-aware order that
does not depend solely on timestamps (which can collide within a batch). It is
nullable so rows written before this migration remain valid; consumers order
by (timestamp, seq, id).
"""

import sqlalchemy as sa

from alembic import op

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('events') as batch_op:
        batch_op.add_column(sa.Column('seq', sa.Integer(), nullable=True))
        batch_op.create_index('ix_events_seq', ['seq'])


def downgrade() -> None:
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_index('ix_events_seq')
        batch_op.drop_column('seq')
