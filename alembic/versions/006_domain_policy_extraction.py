"""domain policy extraction

Revision ID: 006_domain_policy_extraction
Revises: 005_asset_performance
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006_domain_policy_extraction"
down_revision = "005_asset_performance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domain_policies", sa.Column("search_url_template", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("user_url_template", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("result_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("title_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("login_url", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("login_email_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("login_password_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("login_submit_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("login_success_selector", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("credential_email", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("credential_password", sa.Text(), nullable=True))
    op.add_column("domain_policies", sa.Column("accepted_extensions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[\"mp4\",\"webm\",\"m3u8\",\"mpd\"]'::jsonb")))
    op.add_column("domain_policies", sa.Column("is_adult", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("domain_policies", sa.Column("requires_login", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("domain_policies", sa.Column("needs_media_interception", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("domain_policies", sa.Column("title_suffix_strips", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    for name in [
        "title_suffix_strips",
        "needs_media_interception",
        "requires_login",
        "is_adult",
        "accepted_extensions",
        "credential_password",
        "credential_email",
        "login_success_selector",
        "login_submit_selector",
        "login_password_selector",
        "login_email_selector",
        "login_url",
        "title_selector",
        "result_selector",
        "user_url_template",
        "search_url_template",
    ]:
        op.drop_column("domain_policies", name)
