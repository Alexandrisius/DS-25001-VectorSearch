"""Схемы импорта и фоновых задач."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ImportRequest(BaseModel):
    collection_name: str
    data: list[dict[str, Any]] = Field(..., description="[{code, description, hierarchy?, meta?}]")
    recreate: bool = False
    folders_to_delete: list[str] = Field(
        default_factory=list,
        description="Список full_path папок для удаления (опционально)",
    )


class ImportResponse(BaseModel):
    job_id: str
    status: str = "queued"


class JobInfo(BaseModel):
    id: str
    type: str
    status: str
    progress: int
    total: int
    details: str
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: str | None
    started_at: str | None
    finished_at: str | None


class JobListResponse(BaseModel):
    jobs: list[JobInfo] = []


class UploadExcelResponse(BaseModel):
    filename: str
    sheets: list[str]
    selected_sheet: str
    headers: list[str]
    preview: list[dict[str, Any]]
    preview_raw: list[dict[str, Any]] | None = None
    total_rows: int
    cache_key: str
