"""ApiProvider — конфигурация внешних API (OpenRouter и др.)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class ApiProvider(Base):
    """Конфигурация внешнего провайдера эмбеддингов / rerank.

    api_key хранится в зашифрованном виде (Fernet).
    """

    __tablename__ = "api_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    model_embed: Mapped[str] = mapped_column(
        String(128), nullable=False, default="qwen/qwen3-embedding-4b"
    )
    model_rerank: Mapped[str] = mapped_column(
        String(128), nullable=False, default="qwen/qwen3-rerank-8b"
    )
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    max_workers: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def to_dict(self, *, include_key: bool = False, decrypted_key: str = "") -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "enabled": self.enabled,
            "api_key_set": bool(self.api_key_encrypted),
            "model_embed": self.model_embed,
            "model_rerank": self.model_rerank,
            "batch_size": self.batch_size,
            "max_workers": self.max_workers,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_key and decrypted_key:
            d["api_key"] = decrypted_key
        return d
