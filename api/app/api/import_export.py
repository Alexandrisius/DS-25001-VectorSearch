"""Import/Export API — /admin/import, /admin/upload_excel, /admin/excel_data."""
from __future__ import annotations

import json
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

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
    """Запуск фоновой задачи импорта (через Celery)."""
    job_svc = JobService(session)
    coll = await CollectionService(session).get_or_404(req.collection_name)

    records = req.get_records()

    job = await job_svc.create(
        job_type="import_batch",
        params={
            "collection_name": req.collection_name,
            "total_records": len(records),
            "recreate": req.recreate,
            "folders_to_delete": req.folders_to_delete,
        },
    )
    await session.commit()  # фиксируем job_id

    # Запускаем Celery
    import_task.delay(
        job_id=str(job.id),
        collection_id=coll.id,
        records=records,
    )
    return ImportResponse(job_id=str(job.id), status="queued")


@router.post("/upload_excel", response_model=UploadExcelResponse)
async def admin_upload_excel(
    file: UploadFile = File(...),
    sheet: str | None = None,
    session: DBSession = None,
    _: dict = Depends(get_current_admin),
) -> UploadExcelResponse:
    """Загрузка Excel с preview + кэшированием данных для последующего импорта."""
    result = await parse_excel(file, sheet=sheet, preview_rows=100)
    cache_key = uuid_mod.uuid4().hex[:16]
    # Сохраняем все данные в app.state (in-memory cache)
    from fastapi import Request as _Req

    # Простой способ — положим в redis (TODO) или app.state
    # Здесь — сохраним в app.state через Depends
    if not hasattr(_app_state_holder, "excel_cache"):
        _app_state_holder.excel_cache = {}
    _app_state_holder.excel_cache[cache_key] = {
        "headers": result["headers"],
        "data": result["data"],
        "filename": result["filename"],
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if len(_app_state_holder.excel_cache) > 5:
        first = next(iter(_app_state_holder.excel_cache))
        _app_state_holder.excel_cache.pop(first, None)
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
    if not hasattr(_app_state_holder, "excel_cache") or cache_key not in _app_state_holder.excel_cache:
        raise HTTPException(
            status_code=404, detail="Данные не найдены в кэше. Загрузите файл заново."
        )
    cached = _app_state_holder.excel_cache[cache_key]
    return {
        "headers": cached["headers"],
        "data": cached["data"],
        "total_rows": len(cached["data"]),
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
                status=j.status,
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


# Placeholder для app.state (заполняется в main.py)
class _AppStateHolder:
    excel_cache: dict = {}


_app_state_holder = _AppStateHolder()
