"""Схемы коллекций."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CollectionConfigUpdate(BaseModel):
    visible: bool = True
    thresholds: dict[str, float] = Field(..., description="{'cosine': 0.45, 'rerank': 0.6}")


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
