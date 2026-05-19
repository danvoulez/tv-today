"""Asset performance ficha — play history and health score on library_assets.

Revision ID: 005
Revises: 004
Create Date: 2026-05-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("library_assets", sa.Column(
        "error_count", sa.Integer(), nullable=False, server_default="0"
    ))
    op.add_column("library_assets", sa.Column(
        "health_score", sa.Numeric(4, 3), nullable=False, server_default="1.000"
    ))
    op.add_column("library_assets", sa.Column(
        "last_play_status", sa.String(20), nullable=True
    ))
    op.add_column("library_assets", sa.Column(
        "play_log", JSONB(), nullable=False, server_default="[]"
    ))


def downgrade() -> None:
    op.drop_column("library_assets", "play_log")
    op.drop_column("library_assets", "last_play_status")
    op.drop_column("library_assets", "health_score")
    op.drop_column("library_assets", "error_count")
