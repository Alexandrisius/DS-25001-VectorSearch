"""Базовые миксины для моделей."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class TimestampMixin:
    """Mixin: created_at + updated_at с автозаполнением."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


__all__ = ["Base", "TimestampMixin"]
