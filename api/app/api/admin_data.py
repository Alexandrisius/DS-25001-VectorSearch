"""Admin data API — inline-редактирование записей коллекции."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http import models as qm
from sqlalchemy import select

from app.deps import DBSession, get_current_admin, get_qdrant
from app.models.material import Material
from app.schemas.material import UpdateCellRequest
from app.services.collection_service import CollectionService
from app.services.folder_service import FolderService
from app.di import get_folder_service, get_material_service

router = APIRouter(prefix="/admin", tags=["admin-data"])


@router.get("/collections/{name}/data")
async def admin_get_data(
    name: str,
    limit: int = 50,
    offset: str | None = None,
    session: DBSession = None,
    _: dict = Depends(get_current_admin),
) -> dict:
    coll = await CollectionService(session).get_or_404(name)
    qdrant = get_qdrant()
    points, next_offset = qdrant.scroll(
        collection_name=coll.name,
        limit=limit,
        offset=offset,
        with_payload=True,
        with_vectors=False,
        scroll_filter=qm.Filter(
            must_not=[
                qm.FieldCondition(key="is_folder", match=qm.MatchValue(value=True))
            ]
        ),
    )
    max_path_depth = 0
    data = []
    for p in points:
        payload = p.payload or {}
        d = payload.get("path_depth", 0)
        if d > max_path_depth:
            max_path_depth = d
        data.append(
            {
                "id": str(p.id),
                "code": payload.get("code", ""),
                "description": payload.get("description", ""),
                "meta": payload,
            }
        )
    # Получить total из Postgres
    result = await session.execute(
        select(Material).where(Material.collection_id == coll.id)
    )
    total = len(result.scalars().all())
    return {
        "data": data,
        "next_offset": next_offset,
        "total": total,
        "max_path_depth": max_path_depth,
    }


@router.post("/collections/{name}/data/{id}")
async def admin_update_point(
    name: str,
    id: str,
    req: UpdateCellRequest,
    session: DBSession = None,
    _: dict = Depends(get_current_admin),
) -> dict:
    coll = await CollectionService(session).get_or_404(name)
    from uuid import UUID

    try:
        point_uuid = UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid point id")

    # Найти material в Postgres
    result = await session.execute(
        select(Material).where(Material.qdrant_point_id == point_uuid)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    from app.di import get_embedding_service
    from app.services.material_service import MaterialService

    embedding = await get_embedding_service(session)
    mat_svc = MaterialService(session, embedding_service=embedding)
    material = await mat_svc.update_cell(material, coll, req.field, req.value)

    # Синхронизация папок при изменении path_level
    folder_sync = None
    if req.field.startswith("path_level_"):
        folder_svc = get_folder_service(session, embedding=embedding)
        # Простая версия: вычислить текущий полный путь
        from app.services.material_service import deterministic_uuid
        from app.services.folder_service import deterministic_folder_uuid
        try:
            folder_sync = await folder_svc.check_orphans_after_delete(coll, material)
        except Exception as e:
            folder_sync = {"error": str(e)}

    return {
        "status": "success",
        "id": str(material.qdrant_point_id),
        "context_description": material.context_description,
        "updated_at": material.updated_at.isoformat() if material.updated_at else None,
        "version": material.version,
        "folder_sync": folder_sync,
    }


@router.delete("/collections/{name}/data/{id}")
async def admin_delete_point(
    name: str,
    id: str,
    session: DBSession = None,
    _: dict = Depends(get_current_admin),
) -> dict:
    coll = await CollectionService(session).get_or_404(name)
    from uuid import UUID

    try:
        point_uuid = UUID(id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid point id")

    result = await session.execute(
        select(Material).where(Material.qdrant_point_id == point_uuid)
    )
    material = result.scalar_one_or_none()
    if not material:
        raise HTTPException(status_code=404, detail="Material not found")

    from app.services.material_service import MaterialService
    mat_svc = MaterialService(session)
    await mat_svc.delete(material, coll)

    # Проверить осиротевшие папки
    from app.di import get_embedding_service
    embedding = await get_embedding_service(session)
    folder_svc = FolderService(session, embedding_service=embedding)
    deleted_folders = await folder_svc.check_orphans_after_delete(coll, material)

    return {
        "status": "success",
        "deleted_id": str(point_uuid),
        "deleted_folders": deleted_folders,
    }
