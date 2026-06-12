"""add base_url to api_providers

Revision ID: 0002_add_base_url
Revises: 0001_init_schema
Create Date: 2026-06-11 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_base_url"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_providers",
        sa.Column("base_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("api_providers", "base_url")
