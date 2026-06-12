"""Materials API — /update_record, /update_batch_records, /delete_*, /get_all_codes, /get_all_folders."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from qdrant_client.http import models as qm
from sqlalchemy import select

from app.deps import DBSession, get_qdrant
from app.models.material import Material
from app.schemas.material import (
    BatchDeleteRequest,
    BatchUpdateRequest,
    UpdateRequest,
)
from app.services.collection_service import CollectionService

router = APIRouter(tags=["materials"])


# ------------------------------------------------------------------ public
@router.post("/update_record")
async def update_record(
    request: UpdateRequest,
    req: Request,
    session: DBSession,
) -> dict:
    """Обновить одну запись (генерирует новый эмбеддинг)."""
    from app.di import get_embedding_service
    from app.services.material_service import MaterialService

    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(request.database or (await coll_svc.get_current_active(None)).name)

    embedding = await get_embedding_service(req)
    mat_svc = MaterialService(session, embedding_service=embedding)
    await mat_svc.upsert(coll, request.code, request.description)
    coll.last_updated = request.database  # type: ignore[assignment]
    return {"status": "success", "message": f"Запись '{request.code}' обновлена", "database": coll.name}


@router.post("/update_batch_records")
async def update_batch_records(
    request: BatchUpdateRequest,
    req: Request,
    session: DBSession,
) -> dict:
    """Пакетное обновление (синхронное)."""
    from app.di import get_embedding_service
    from app.services.material_service import MaterialService

    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(request.database or (await coll_svc.get_current_active(None)).name)

    embedding = await get_embedding_service(req)
    mat_svc = MaterialService(session, embedding_service=embedding)
    count = 0
    for r in request.records:
        await mat_svc.upsert(coll, r.code, r.description)
        count += 1
    return {
        "status": "success",
        "processed": count,
        "database": coll.name,
    }


@router.post("/delete_batch_records")
async def delete_batch_records(request: BatchDeleteRequest, session: DBSession) -> dict:
    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(request.database or (await coll_svc.get_current_active(None)).name)
    qdrant = get_qdrant()
    qdrant.delete(
        collection_name=coll.name,
        points_selector=qm.Filter(
            must=[qm.FieldCondition(key="code", match=qm.MatchAny(any=request.codes))]
        ),
    )
    # Удалить из Postgres
    from sqlalchemy import delete
    await session.execute(
        delete(Material).where(
            Material.collection_id == coll.id,
            Material.code.in_(request.codes),
        )
    )
    await session.flush()
    return {"status": "success", "message": f"Удалено {len(request.codes)} записей"}


@router.delete("/delete_record/{code}")
async def delete_record(code: str, database: str | None = None, session: DBSession = None) -> dict:
    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(database or (await coll_svc.get_current_active(None)).name)
    qdrant = get_qdrant()
    qdrant.delete(
        collection_name=coll.name,
        points_selector=qm.Filter(
            must=[qm.FieldCondition(key="code", match=qm.MatchValue(value=code))]
        ),
    )
    from sqlalchemy import delete
    await session.execute(
        delete(Material).where(
            Material.collection_id == coll.id,
            Material.code == code,
        )
    )
    await session.flush()
    return {"status": "success", "message": f"Запись '{code}' удалена"}


# ------------------------------------------------------------------ read
@router.get("/get_all_codes")
async def get_all_codes(
    database: str | None = None,
    session: DBSession = None,
) -> dict:
    """Все коды + описания (для diff при импорте)."""
    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(database or (await coll_svc.get_current_active(None)).name)

    qdrant = get_qdrant()
    records: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=coll.name,
            limit=2000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
            scroll_filter=qm.Filter(
                must_not=[
                    qm.FieldCondition(key="is_folder", match=qm.MatchValue(value=True))
                ]
            ),
        )
        for p in points:
            payload = p.payload or {}
            code = payload.get("code")
            if not code:
                continue
            full = payload.get("full_description") or payload.get("description", "")
            d = {
                "description": full,
                "full_description": full,
                "code": code,
                "path_depth": payload.get("path_depth", 0),
            }
            for i in range(1, payload.get("path_depth", 0) + 1):
                d[f"path_level_{i}"] = payload.get(f"path_level_{i}", "")
            records[code] = d
        if offset is None:
            break
    return {
        "status": "success",
        "collection": coll.name,
        "records": records,
        "total": len(records),
    }


@router.get("/get_all_folders")
async def get_all_folders(database: str | None = None, session: DBSession = None) -> dict:
    coll_svc = CollectionService(session)
    coll = await coll_svc.get_or_404(database or (await coll_svc.get_current_active(None)).name)
    qdrant = get_qdrant()
    folders: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        points, offset = qdrant.scroll(
            collection_name=coll.name,
            limit=2000,
            offset=offset,
            with_payload=["full_path", "leaf_name", "items_count", "path_depth", "code"],
            with_vectors=False,
            scroll_filter=qm.Filter(
                must=[qm.FieldCondition(key="is_folder", match=qm.MatchValue(value=True))]
            ),
        )
        for p in points:
            payload = p.payload or {}
            fp = payload.get("full_path")
            if fp:
                folders[fp] = {
                    "id": str(p.id),
                    "leaf_name": payload.get("leaf_name", ""),
                    "items_count": payload.get("items_count", 0),
                    "path_depth": payload.get("path_depth", 1),
                    "code": payload.get("code", ""),
                }
        if offset is None:
            break
    return {
        "status": "success",
        "collection": coll.name,
        "folders": folders,
        "total": len(folders),
    }
