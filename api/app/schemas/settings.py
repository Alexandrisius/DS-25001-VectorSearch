"""Схемы настроек (статусы, правила, провайдеры)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StatusConfig(BaseModel):
    id: str
    label: str
    color: str


class StatusConfigOut(BaseModel):
    id: str
    label: str
    color: str
    is_default: bool
    sort_order: int


class StatusesUpdateRequest(BaseModel):
    statuses: list[StatusConfig]
    default_status: str


class CleaningRuleOut(BaseModel):
    id: int
    name: str | None
    pattern: str
    replacement: str
    enabled: bool
    apply_to_columns: list[str]
    sort_order: int


class CleaningRuleUpdate(BaseModel):
    id: int | None = None
    name: str
    pattern: str
    replacement: str = ""
    enabled: bool = True
    apply_to_columns: list[str] = Field(default_factory=lambda: ["*"])
    sort_order: int = 0


class ApiProviderOut(BaseModel):
    name: str
    enabled: bool
    api_key: str  # маскированный
    api_key_set: bool
    base_url: str | None = None
    model_embed: str
    model_rerank: str
    batch_size: int
    max_workers: int
    updated_at: str | None = None


class ApiProviderUpdate(BaseModel):
    enabled: bool = False
    api_key: str = ""
    base_url: str | None = None
    model_embed: str = "qwen/qwen3-embedding-4b"
    model_rerank: str = "cohere/rerank-4-pro"
    batch_size: int = 10
    max_workers: int = 3
