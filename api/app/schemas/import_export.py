"""Схемы импорта и фоновых задач."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ColumnMapping(BaseModel):
    """Маппинг колонок Excel → стандартные поля записи.

    Применяется на сервере (в Celery worker) к raw records из Redis.
    Склеивает несколько колонок в одно поле через separator.
    Пример: code: ["Код КСР", "Номер материала ЕХ"], code_separator: "."
    """
    code: list[str] = Field(default_factory=list)
    description: list[str] = Field(default_factory=list)
    hierarchy: list[str] = Field(default_factory=list)
    code_separator: str = "."
    description_separator: str = " "


class ImportRequest(BaseModel):
    """Запрос на импорт записей.

    Поддерживает 3 варианта получения данных:
    1. cache_key: данные лежат в Redis (рекомендуется для >10k строк)
    2. records: алиас для data (новое имя в UI v2.1.0)
    3. data: старое имя поля (v1/v2)
    """
    collection_name: str
    cache_key: str | None = Field(
        default=None,
        description="Ключ в Redis с данными Excel (рекомендуется для больших файлов)",
    )
    data: list[dict[str, Any]] | None = Field(
        default=None,
        description="[{code, description, hierarchy?, meta?}] (старое имя поля)",
    )
    records: list[dict[str, Any]] | None = Field(
        default=None,
        description="Алиас для data (новое имя в UI)",
    )
    column_mapping: ColumnMapping | None = Field(
        default=None,
        description="Маппинг колонок Excel → поля (если cache_key, применяется на сервере)",
    )
    recreate: bool = False
    folders_to_delete: list[str] = Field(
        default_factory=list,
        description="Список full_path папок для удаления (опционально)",
    )

    model_config = ConfigDict(populate_by_name=True)

    def model_post_init(self, __context: Any) -> None:
        # Если передали "records" но не "data", используем records
        if self.data is None and self.records is not None:
            self.data = self.records
        elif self.records is None and self.data is not None:
            self.records = self.data

    def get_records(self) -> list[dict[str, Any]]:
        """Возвращает записи независимо от того, какое поле использовалось."""
        return self.data if self.data is not None else (self.records or [])


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
