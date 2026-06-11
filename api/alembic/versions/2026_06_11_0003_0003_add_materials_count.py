"""add materials_count to collections

Revision ID: 0003_add_materials_count
Revises: 0002_add_base_url
Create Date: 2026-06-11 23:30:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_add_materials_count"
down_revision = "0002_add_base_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column(
            "materials_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Backfill из существующих данных (один SQL, не N запросов)
    op.execute(
        """
        UPDATE collections c
        SET materials_count = COALESCE(sub.cnt, 0)
        FROM (
            SELECT collection_id, COUNT(*) AS cnt
            FROM materials
            WHERE status_id = 'active'
            GROUP BY collection_id
        ) sub
        WHERE c.id = sub.collection_id
        """
    )


def downgrade() -> None:
    op.drop_column("collections", "materials_count")
