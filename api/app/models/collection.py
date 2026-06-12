"""Collection — коллекция Qdrant (метаданные)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Collection(Base):
    """Метаданные коллекции Qdrant."""

    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    columns_mapping: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, default=lambda: {"code": "code", "description": "description"}
    )
    cosine_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.45)
    rerank_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    # ===== Phase 4: RRF + MMR + adaptive threshold =====
    # Reciprocal Rank Fusion weights: relative contribution of dense vs sparse legs.
    # Final fused score = w_dense / (k + rank_dense) + w_bm25 / (k + rank_bm25).
    rrf_k: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    rrf_dense_weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1.0")
    rrf_bm25_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.7, server_default="0.7")
    # Maximal Marginal Relevance: balance between query relevance and diversity.
    # 1.0 = pure relevance, 0.0 = pure diversity. 0.7 is the sweet spot for KSR.
    mmr_lambda: Mapped[float] = mapped_column(Float, nullable=False, default=0.7, server_default="0.7")
    # How many candidates to keep after MMR dedup (cap for rerank).
    mmr_pool_size: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    # Adaptive threshold: if max rerank_score >= this, "confident" → top-10.
    adaptive_confident_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, server_default="0.5")
    # If max rerank_score in [uncertain_min, confident_min) — "uncertain" → top-5 + UI hint.
    adaptive_uncertain_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.15, server_default="0.15")
    # If max rerank_score < uncertain_min — fallback to top-N by cosine similarity.
    fallback_cosine_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.30, server_default="0.30")
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Stored counter — обновляется при импорте (INCREMENT по chunk).
    # Нужен чтобы /admin/collections возвращался мгновенно (без
    # SELECT COUNT(*) по 142k записей при каждом запросе).
    materials_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Связи
    materials: Mapped[list["Material"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    folders: Mapped[list["Folder"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )

    def to_dict(self, *, is_active: bool = False, record_count: int = 0) -> dict[str, Any]:
        """Сериализация в dict.

        ВАЖНО: record_count передаётся извне (из eager-loaded запроса).
        НЕ использовать len(self.materials) здесь — это вызовет MissingGreenlet
        в async контексте после закрытия сессии.
        """
        return {
            "name": self.name,
            "description": self.description or self.name,
            "record_count": record_count,
            "dimension": self.dimension,
            "thresholds": {
                "cosine": self.cosine_threshold,
                "rerank": self.rerank_threshold,
            },
            "phase4": {
                "rrf_k": self.rrf_k,
                "rrf_dense_weight": self.rrf_dense_weight,
                "rrf_bm25_weight": self.rrf_bm25_weight,
                "mmr_lambda": self.mmr_lambda,
                "mmr_pool_size": self.mmr_pool_size,
                "adaptive_confident_min": self.adaptive_confident_min,
                "adaptive_uncertain_min": self.adaptive_uncertain_min,
                "fallback_cosine_min": self.fallback_cosine_min,
            },
            "last_updated": self.last_updated.isoformat() if self.last_updated else "",
            "visible": self.visible,
            "locked": self.locked,
            "is_active": is_active,
        }
