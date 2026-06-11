"""BackgroundJob — фоновая задача (импорт и др.)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class BackgroundJob(Base):
    """Фоновая задача Celery."""

    __tablename__ = "background_jobs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "total": self.total,
            "details": self.details,
            "error": self.error,
            "result": self.result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
