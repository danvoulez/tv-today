"""Runtime control table and production constraints

Revision ID: 004
Revises: 003
Create Date: 2026-05-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "004"
down_revision: Union[str, None] = "003_bridge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stream_control",
        sa.Column("key", sa.String(50), primary_key=True),
        sa.Column("desired_running", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(50), nullable=False, server_default="idle"),
        sa.Column(
            "current_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("stream_plan_items.id"),
            nullable=True,
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_library_assets_source_url",
        "library_assets",
        ["source_url"],
    )
    op.create_unique_constraint(
        "uq_stream_plan_items_plan_sequence",
        "stream_plan_items",
        ["stream_plan_id", "sequence_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_stream_plan_items_plan_sequence", "stream_plan_items", type_="unique")
    op.drop_constraint("uq_library_assets_source_url", "library_assets", type_="unique")
    op.drop_table("stream_control")
