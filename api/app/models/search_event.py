"""SearchEvent — запись каждого /match вызова (аналитика поиска)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class SearchEvent(Base):
    """Событие поиска: запрос, тайминги, атрибуция пользователя, top-результаты."""

    __tablename__ = "search_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # --- атрибуция ---
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- что искали ---
    query: Mapped[str] = mapped_column(Text, nullable=False)
    collection: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filter_paths: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- per-stage тайминги (мс) — типизированные для сортировки/фильтрации ---
    embed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qdrant_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bm25_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rrf_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mmr_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rerank_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    format_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- результат ---
    candidates_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    branch: Mapped[str | None] = mapped_column(String(32), nullable=True)
    top_results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- конфиг (для отладки смены моделей) ---
    model_embed: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_rerank: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # --- статус ---
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="success"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat() if self.ts else None,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "user_ip": self.user_ip,
            "user_agent": self.user_agent,
            "query": self.query,
            "collection": self.collection,
            "filter_paths": self.filter_paths,
            "embed_ms": self.embed_ms,
            "qdrant_ms": self.qdrant_ms,
            "bm25_ms": self.bm25_ms,
            "rrf_ms": self.rrf_ms,
            "mmr_ms": self.mmr_ms,
            "rerank_ms": self.rerank_ms,
            "format_ms": self.format_ms,
            "total_ms": self.total_ms,
            "candidates_count": self.candidates_count,
            "branch": self.branch,
            "top_results": self.top_results,
            "model_embed": self.model_embed,
            "model_rerank": self.model_rerank,
            "status": self.status,
            "error": self.error,
        }


__all__ = ["SearchEvent"]
