"""Import/Export API — /admin/import, /admin/upload_excel, /admin/excel_data."""
from __future__ import annotations

import json
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.cache.excel_cache import (
    CACHE_TTL_SECONDS,
    load_excel_from_cache,
    save_excel_to_cache,
)
from app.core.exceptions import NotFoundError
from app.deps import DBSession, get_current_admin
from app.models.background_job import JobStatus
from app.schemas.import_export import (
    ImportRequest,
    ImportResponse,
    JobInfo,
    JobListResponse,
    UploadExcelResponse,
)
from app.services.collection_service import CollectionService
from app.services.job_service import JobService
from app.utils.excel import parse_excel
from app.workers.tasks import import_task

router = APIRouter(prefix="/admin", tags=["import"])


@router.post("/import", response_model=ImportResponse)
async def admin_import(
    req: ImportRequest,
    session: DBSession,
    _: dict = Depends(get_current_admin),
) -> ImportResponse:
    """Запуск фоновой задачи импорта (через Celery).

    Поддерживает 2 варианта:
    1. cache_key: данные лежат в Redis (рекомендуется для >10k строк)
    2. records/data: данные приходят напрямую (для маленьких импортов или тестов)
    """
    job_svc = JobService(session)
    coll = await CollectionService(session).get_or_404(req.collection_name)

    # Определяем records: либо из cache, либо из payload
    records: list[dict[str, Any]] = []

    if req.cache_key:
        cached = await load_excel_from_cache(req.cache_key)
        if not cached:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Данные по cache_key '{req.cache_key}' не найдены или истекли "
                    f"(TTL {CACHE_TTL_SECONDS} сек). Загрузите Excel заново."
                ),
            )
        records = cached.get("data", [])
        # НЕ удаляем cache здесь — worker удалит после успешного импорта
    else:
        # Fallback: records пришли напрямую
        records = req.get_records()

    if not records:
        raise HTTPException(
            status_code=400,
            detail="Нет данных для импорта (records пустой и cache_key не указан)",
        )

    job = await job_svc.create(
        job_type="import_batch",
        params={
            "collection_name": req.collection_name,
            "total_records": len(records),
            "recreate": req.recreate,
            "folders_to_delete": req.folders_to_delete,
            "cache_key": req.cache_key,  # может быть None
        },
    )
    await session.commit()  # фиксируем job_id

    # Запускаем Celery. Передаём cache_key (если есть) — worker прочитает сам.
    import_task.delay(
        job_id=str(job.id),
        collection_id=coll.id,
        cache_key=req.cache_key,
        records=records,  # fallback если cache_key=None
    )
    return ImportResponse(job_id=str(job.id), status="queued")


@router.post("/upload_excel", response_model=UploadExcelResponse)
async def admin_upload_excel(
    file: UploadFile = File(...),
    sheet: str | None = None,
    session: DBSession = None,
    _: dict = Depends(get_current_admin),
) -> UploadExcelResponse:
    """Загрузка Excel с preview + кэшированием данных в Redis для последующего импорта."""
    result = await parse_excel(file, sheet=sheet, preview_rows=100)
    cache_key = uuid_mod.uuid4().hex[:16]
    # Сохраняем все данные в Redis (TTL 1 час) — общий для API и Celery worker
    await save_excel_to_cache(
        cache_key,
        {
            "headers": result["headers"],
            "data": result["data"],
            "filename": result["filename"],
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    )
    return UploadExcelResponse(
        filename=result["filename"],
        sheets=result["sheets"],
        selected_sheet=result["selected_sheet"],
        headers=result["headers"],
        preview=result["preview"],
        preview_raw=result["preview"],
        total_rows=result["total_rows"],
        cache_key=cache_key,
    )


@router.get("/excel_data/{cache_key}")
async def admin_get_excel_data(
    cache_key: str,
    _: dict = Depends(get_current_admin),
) -> dict:
    """Получить preview данных по cache_key (без полного payload)."""
    cached = await load_excel_from_cache(cache_key)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail=f"Данные не найдены в кэше (TTL {CACHE_TTL_SECONDS} сек). Загрузите файл заново.",
        )
    return {
        "headers": cached["headers"],
        "total_rows": len(cached.get("data", [])),
        "filename": cached.get("filename", ""),
    }


# Job-related
@router.get("/jobs", response_model=JobListResponse)
async def admin_list_jobs(
    session: DBSession,
    _: dict = Depends(get_current_admin),
) -> JobListResponse:
    job_svc = JobService(session)
    jobs = await job_svc.list_all()
    return JobListResponse(
        jobs=[
            JobInfo(
                id=str(j.id),
                type=j.type,
                status=j.status.value if hasattr(j.status, "value") else str(j.status),
                progress=j.progress,
                total=j.total,
                details=j.details,
                error=j.error,
                result=j.result,
                created_at=j.created_at.isoformat() if j.created_at else None,
                started_at=j.started_at.isoformat() if j.started_at else None,
                finished_at=j.finished_at.isoformat() if j.finished_at else None,
            )
            for j in jobs
        ]
    )


@router.post("/jobs/{job_id}/stop")
async def admin_stop_job(
    job_id: str,
    session: DBSession,
    _: dict = Depends(get_current_admin),
) -> dict:
    job_svc = JobService(session)
    ok = await job_svc.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Невозможно остановить задачу")
    return {"status": "success", "message": f"Задача {job_id} остановлена"}


__all__ = ["router"]
