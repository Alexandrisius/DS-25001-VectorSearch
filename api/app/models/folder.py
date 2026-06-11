"""Folder — папка (категория) в иерархии."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres import Base


class Folder(Base):
    """Папка (категория) в иерархии коллекции.

    На каждом уровне вложенности path_level_N — отдельная запись Folder.
    """

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_path: Mapped[str] = mapped_column(Text, nullable=False)
    leaf_name: Mapped[str] = mapped_column(String(256), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("folders.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    items_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qdrant_point_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Связи
    collection: Mapped["Collection"] = relationship(back_populates="folders")  # noqa: F821
    parent: Mapped["Folder | None"] = relationship(
        "Folder", remote_side="Folder.id", backref="children"
    )
    material_links: Mapped[list["MaterialFolder"]] = relationship(  # noqa: F821
        back_populates="folder", cascade="all, delete-orphan"
    )

    __table_args__ = ()  # UniqueConstraint создан миграцией

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "full_path": self.full_path,
            "leaf_name": self.leaf_name,
            "level": self.level,
            "items_count": self.items_count,
            "parent_id": self.parent_id,
        }
