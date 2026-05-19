"""Add bridge traceability columns.

- candidate_assets.library_asset_id nullable FK to library_assets.id
- lineup_runs.stream_plan_id nullable FK to stream_plans.id

Revision ID: 003_bridge
Revises: 002_acquisition
Create Date: 2026-05-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "003_bridge"
down_revision = "002_acquisition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_assets",
        sa.Column(
            "library_asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("library_assets.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "lineup_runs",
        sa.Column(
            "stream_plan_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stream_plans.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("lineup_runs", "stream_plan_id")
    op.drop_column("candidate_assets", "library_asset_id")
