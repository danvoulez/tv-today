"""director tables
Revision ID: 007_director
Revises: 006_domain_policy_extraction
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision='007_director'
down_revision='006_domain_policy_extraction'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('director_runs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('state_snapshot', JSONB, nullable=False, server_default='{}'),
        sa.Column('llm_response', JSONB, nullable=False, server_default='{}'),
        sa.Column('action_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
    )
    op.create_table('director_actions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('director_runs.id'), nullable=False),
        sa.Column('sequence_index', sa.Integer(), nullable=False),
        sa.Column('verb', sa.String(length=50), nullable=False),
        sa.Column('args', JSONB, nullable=False, server_default='{}'),
        sa.Column('why', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('result', JSONB, nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

def downgrade():
    op.drop_table('director_actions'); op.drop_table('director_runs')
