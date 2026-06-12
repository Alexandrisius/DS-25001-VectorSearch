"""Phase 4: RRF + MMR + adaptive threshold fields to collections.

Adds 8 new fields used by the new search pipeline (see search_service.py):
- rrf_k, rrf_dense_weight, rrf_bm25_weight: Reciprocal Rank Fusion
- mmr_lambda, mmr_pool_size: Maximal Marginal Relevance dedup
- adaptive_confident_min, adaptive_uncertain_min: per-query adaptive rerank threshold
- fallback_cosine_min: minimum cosine when rerank falls back

Old fields (cosine_threshold, rerank_threshold) are kept for backward
compatibility but are no longer used in the search pipeline (replaced by
adaptive logic). They will be hidden from the admin UI.

Revision ID: 0004_phase4_rrf_mmr
Revises: 0003
Create Date: 2026-06-12 15:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_phase4_rrf_mmr"
down_revision = "0003_add_materials_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column("rrf_k", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column(
        "collections",
        sa.Column(
            "rrf_dense_weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
    )
    op.add_column(
        "collections",
        sa.Column(
            "rrf_bm25_weight",
            sa.Float(),
            nullable=False,
            server_default="0.7",
        ),
    )
    op.add_column(
        "collections",
        sa.Column("mmr_lambda", sa.Float(), nullable=False, server_default="0.7"),
    )
    op.add_column(
        "collections",
        sa.Column(
            "mmr_pool_size",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "collections",
        sa.Column(
            "adaptive_confident_min",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
    )
    op.add_column(
        "collections",
        sa.Column(
            "adaptive_uncertain_min",
            sa.Float(),
            nullable=False,
            server_default="0.15",
        ),
    )
    op.add_column(
        "collections",
        sa.Column(
            "fallback_cosine_min",
            sa.Float(),
            nullable=False,
            server_default="0.30",
        ),
    )


def downgrade() -> None:
    op.drop_column("collections", "fallback_cosine_min")
    op.drop_column("collections", "adaptive_uncertain_min")
    op.drop_column("collections", "adaptive_confident_min")
    op.drop_column("collections", "mmr_pool_size")
    op.drop_column("collections", "mmr_lambda")
    op.drop_column("collections", "rrf_bm25_weight")
    op.drop_column("collections", "rrf_dense_weight")
    op.drop_column("collections", "rrf_k")
