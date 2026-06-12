"""FeedbackEvent — аналитика (копирование, дизлайки)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class FeedbackEvent(Base):
    """Событие обратной связи (лайк/дизлайк/копирование)."""

    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reranker_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cosine_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
