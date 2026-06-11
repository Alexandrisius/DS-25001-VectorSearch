"""Material — материал (зеркало Qdrant для SQL-фильтрации)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Material(Base):
    """Запись материала.

    Зеркало Qdrant для SQL-фильтрации (по status, version, code, etc.).
    Полный payload хранится в Qdrant, в Postgres — критичные для фильтрации поля.
    """

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    path_levels: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    path_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    qdrant_point_id: Mapped[UUID] = mapped_column(PG_UUID(astext_type=Text), nullable=False)
    status_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("statuses.id"), nullable=False, default="active", server_default="active"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Связи
    collection: Mapped["Collection"] = relationship(back_populates="materials")  # noqa: F821
    folder_links: Mapped[list["MaterialFolder"]] = relationship(  # noqa: F821
        back_populates="material", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # UniqueConstraint создаётся миграцией явно
    )

    def to_payload_dict(self) -> dict[str, Any]:
        """Payload для Qdrant."""
        from app.utils.path_levels import build_full_path

        full_path = build_full_path(self.path_levels or {}) if self.path_levels else ""
        result: dict[str, Any] = {
            "code": self.code,
            "description": self.description or "",
            "full_description": self.full_description or "",
            "context_description": self.context_description or "",
            "path_depth": self.path_depth,
            "status": self.status_id,
            "version": self.version,
        }
        if full_path:
            result["full_path"] = full_path
        if self.path_levels:
            result.update(self.path_levels)
        return result
