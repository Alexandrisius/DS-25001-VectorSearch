"""Status — справочник статусов записей."""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Status(Base):
    """Справочник статусов (active, draft, deprecated, custom)."""

    __tablename__ = "statuses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<Status {self.id} ({self.label})>"
