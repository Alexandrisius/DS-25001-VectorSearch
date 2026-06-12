"""Схемы материалов и поиска."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FilterPath(BaseModel):
    path: str
    level: int | None = None


class MatchRequest(BaseModel):
    text: str = Field(..., min_length=1)
    database: str | None = None
    filter_path: str | None = None
    filter_level: int | None = None
    filter_paths: list[FilterPath] | None = None
    top_k: int | None = None


class CandidateResult(BaseModel):
    rank: int
    code: str
    description: str
    material_name: str | None = None
    category_path: str | None = None
    reranker_score: float
    cosine_similarity: float


class SearchTrace(BaseModel):
    """Диагностика пайплайна поиска (Phase 4: RRF + MMR + adaptive)."""
    stages: list[dict[str, Any]] = Field(default_factory=list)
    rrf: dict[str, Any] = Field(default_factory=dict)
    rrf_fused_top10: list[dict[str, Any]] = Field(default_factory=list)
    mmr: dict[str, Any] = Field(default_factory=dict)
    adaptive: dict[str, Any] = Field(default_factory=dict)
    adaptive_branch: str | None = None
    adaptive_limit: int | None = None
    max_rerank_score: float | None = None
    final_count: int | None = None


class MatchResponse(BaseModel):
    query: str
    database: str
    candidates: list[CandidateResult]
    processing_time: float
    status: str
    # Phase 4: дебаг-информация и UI-хинт
    search_trace: SearchTrace | None = None
    hint: str | None = None


class MatchResponsePublic(MatchResponse):
    """Алиас — для обратной совместимости с UI."""


class MaterialInfo(BaseModel):
    id: int
    code: str
    description: str | None = None
    full_description: str | None = None
    path_levels: dict[str, Any] | None = None
    path_depth: int = 0
    status_id: str = "active"
    version: int = 1
    qdrant_point_id: str | None = None


class UpdateRequest(BaseModel):
    code: str
    description: str
    database: str | None = None


class BatchUpdateItem(BaseModel):
    code: str
    description: str


class BatchUpdateRequest(BaseModel):
    records: list[BatchUpdateItem]
    database: str | None = None


class BatchDeleteRequest(BaseModel):
    codes: list[str]
    database: str | None = None


class UpdateCellRequest(BaseModel):
    """PATCH одной ячейки материала (admin)."""
    code: str | None = None
    field: str
    value: str


class UpdatePointResponse(BaseModel):
    status: str
    id: str
    context_description: str | None = None
    updated_at: str | None = None
    version: int | None = None
    folder_sync: dict[str, Any] | None = None
