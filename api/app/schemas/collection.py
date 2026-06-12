"""Схемы коллекций."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CollectionConfigUpdate(BaseModel):
    visible: bool = True
    # Legacy thresholds (оставлены для обратной совместимости, но
    # Phase 4 search их не использует — adaptive threshold решает).
    thresholds: dict[str, float] = Field(
        default_factory=lambda: {"cosine": 0.45, "rerank": 0.6},
        description="Legacy {'cosine': 0.45, 'rerank': 0.6} — not used by Phase 4",
    )
    # Phase 4: RRF + MMR + adaptive threshold
    phase4: dict[str, Any] | None = Field(
        default=None,
        description=(
            "{'rrf_k': 60, 'rrf_dense_weight': 1.0, 'rrf_bm25_weight': 0.7, "
            "'mmr_lambda': 0.7, 'mmr_pool_size': 100, "
            "'adaptive_confident_min': 0.5, 'adaptive_uncertain_min': 0.15, "
            "'fallback_cosine_min': 0.30}"
        ),
    )


class DatabaseInfo(BaseModel):
    name: str
    description: str
    record_count: int
    dimension: int
    thresholds: dict[str, float]
    last_updated: str = ""


class DatabasesResponse(BaseModel):
    databases: list[DatabaseInfo]
    current_database: str | None


class CollectionInfo(BaseModel):
    name: str
    description: str
    record_count: int
    dimension: int
    thresholds: dict[str, float]
    last_updated: str = ""
    visible: bool = True
    locked: bool = False
    is_active: bool = False
    # Phase 4: RRF + MMR + adaptive threshold (опционально,
    # появляется когда Collection имеет эти поля)
    phase4: dict[str, Any] | None = None


class CollectionListResponse(BaseModel):
    collections: list[CollectionInfo]


class CreateCollectionRequest(BaseModel):
    collection_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    dimension: int = Field(default=0, description="0 = автоопределение от провайдера")
    description: str = ""
    recreate: bool = False

    @field_validator("collection_name")
    @classmethod
    def _no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Имя коллекции не должно содержать пробелов")
        return v


class CollectionConfig(BaseModel):
    """Внутренняя — для PUT /admin/collections/{name}/config."""
    visible: bool
    thresholds: dict[str, float]
