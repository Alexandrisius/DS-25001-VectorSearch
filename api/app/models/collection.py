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
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Связи
    materials: Mapped[list["Material"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )
    folders: Mapped[list["Folder"]] = relationship(  # noqa: F821
        back_populates="collection", cascade="all, delete-orphan"
    )

    def to_dict(self, *, is_active: bool = False) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description or self.name,
            "record_count": len(self.materials) if self.materials else 0,
            "dimension": self.dimension,
            "thresholds": {
                "cosine": self.cosine_threshold,
                "rerank": self.rerank_threshold,
            },
            "last_updated": self.last_updated.isoformat() if self.last_updated else "",
            "visible": self.visible,
            "locked": self.locked,
            "is_active": is_active,
        }
