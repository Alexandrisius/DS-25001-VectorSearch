"""Схемы иерархии категорий."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HierarchyNode(BaseModel):
    name: str
    path: str
    level: int
    count: int = 0
    children: list["HierarchyNode"] = Field(default_factory=list)
    is_category: bool = True
    has_materials: bool = False
    has_children: bool = False
    code: str | None = None
    codes: list[str] | None = None
    materials: list[dict[str, Any]] | None = None
    materials_count: int | None = None


HierarchyNode.model_rebuild()


class HierarchyResponse(BaseModel):
    tree: list[HierarchyNode]
    total_categories: int
    total_items: int
    max_depth: int
    cached: bool = False
    cache_age: int | None = None
    build_time: float | None = None


class HierarchyChildrenResponse(BaseModel):
    children: list[dict[str, Any]]
    materials: list[dict[str, Any]] = []
    parent_path: str
    total: int
    cached: bool = False


class HierarchySearchRequest(BaseModel):
    text: str = Field(..., min_length=1)
    top_k: int = 10


class HierarchyCategoryResult(BaseModel):
    path: str
    name: str
    level: int
    items_count: int
    cosine_score: float | None = None
    rerank_score: float | None = None


class HierarchySearchResponse(BaseModel):
    categories: list[HierarchyCategoryResult]
    query: str
    total_found: int
