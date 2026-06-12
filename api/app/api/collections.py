"""Collections admin API — /admin/collections/* + /create_collection, /upload_batch."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from qdrant_client.http import models as qm
from sqlalchemy import func, select

from app.deps import DBSession, get_current_admin, get_qdrant
from app.models.material import Material
from app.schemas.collection import (
    CollectionConfigUpdate,
    CollectionInfo,
    CollectionListResponse,
    CreateCollectionRequest,
)
from app.services.collection_service import CollectionService
from app.di import get_collection_service

router = APIRouter(tags=["collections"])


@router.get("/admin/collections", response_model=CollectionListResponse)
async def admin_list_collections(
    session: DBSession,
    _: dict = Depends(get_current_admin),
    svc: CollectionService = Depends(get_collection_service),
) -> CollectionListResponse:
    all_coll = await svc.list_all()
    current = await svc.get_current_active(None)

    # Используем stored counter (materials_count) — мгновенный ответ.
    # Counter обновляется при импорте в _upsert_materials_bulk.
    # Fallback: если по какой-то причине counter = 0 а записей много —
    # используем реальный COUNT (для коллекций созданных до миграции 0003).
    from app.models.collection import Collection
    coll_ids = [c.id for c in all_coll]
    counts_by_id: dict[int, int] = {}
    if coll_ids:
        # Stored counters
        for c in all_coll:
            counts_by_id[c.id] = c.materials_count or 0
        # Если counter = 0 для всех — fallback на COUNT
        if all((c.materials_count or 0) == 0 for c in all_coll):
            rows = await session.execute(
                select(Material.collection_id, func.count(Material.id))
                .where(Material.collection_id.in_(coll_ids))
                .where(Material.status_id == "active")
                .group_by(Material.collection_id)
            )
            for cid, cnt in rows.all():
                counts_by_id[cid] = cnt

    return CollectionListResponse(
        collections=[
            CollectionInfo(
                name=c.name,
                description=c.description or c.name,
                record_count=counts_by_id.get(c.id, 0),
                dimension=c.dimension,
                thresholds={
                    "cosine": c.cosine_threshold,
                    "rerank": c.rerank_threshold,
                },
                last_updated=c.last_updated.isoformat() if c.last_updated else "",
                visible=c.visible,
                locked=c.locked,
                is_active=(current.name == c.name if current else False),
                phase4={
                    "rrf_k": c.rrf_k,
                    "rrf_dense_weight": c.rrf_dense_weight,
                    "rrf_bm25_weight": c.rrf_bm25_weight,
                    "mmr_lambda": c.mmr_lambda,
                    "mmr_pool_size": c.mmr_pool_size,
                    "adaptive_confident_min": c.adaptive_confident_min,
                    "adaptive_uncertain_min": c.adaptive_uncertain_min,
                    "fallback_cosine_min": c.fallback_cosine_min,
                },
            )
            for c in all_coll
        ]
    )


@router.post("/admin/collections/{name}/config")
async def admin_update_config(
    name: str,
    config: CollectionConfigUpdate,
    session: DBSession,
    _: dict = Depends(get_current_admin),
    svc: CollectionService = Depends(get_collection_service),
) -> dict:
    phase4 = config.phase4 or {}
    coll = await svc.update_config(
        name,
        visible=config.visible,
        cosine_threshold=config.thresholds.get("cosine"),
        rerank_threshold=config.thresholds.get("rerank"),
        rrf_k=phase4.get("rrf_k"),
        rrf_dense_weight=phase4.get("rrf_dense_weight"),
        rrf_bm25_weight=phase4.get("rrf_bm25_weight"),
        mmr_lambda=phase4.get("mmr_lambda"),
        mmr_pool_size=phase4.get("mmr_pool_size"),
        adaptive_confident_min=phase4.get("adaptive_confident_min"),
        adaptive_uncertain_min=phase4.get("adaptive_uncertain_min"),
        fallback_cosine_min=phase4.get("fallback_cosine_min"),
    )
    # НЕ вызываем coll.to_dict() — это вызовет MissingGreenlet (lazy load).
    # Собираем dict вручную с eager-loaded count.
    from sqlalchemy import func, select
    from app.models.material import Material
    count_result = await session.execute(
        select(func.count(Material.id)).where(Material.collection_id == coll.id)
    )
    record_count = count_result.scalar() or 0
    return {
        "status": "success",
        "config": coll.to_dict(record_count=record_count),
    }


@router.delete("/admin/collections/{name}")
async def admin_delete_collection(
    name: str,
    session: DBSession,
    _: dict = Depends(get_current_admin),
    svc: CollectionService = Depends(get_collection_service),
) -> dict:
    await svc.delete(name)
    return {"status": "success", "message": f"Коллекция '{name}' удалена"}


@router.post("/create_collection")
async def create_collection(
    request: CreateCollectionRequest,
    session: DBSession,
    svc: CollectionService = Depends(get_collection_service),
) -> dict:
    """Создать коллекцию (Qdrant + Postgres). Публичный для совместимости с UI."""
    # Определяем dimension
    if request.dimension <= 0:
        dim = await svc.determine_dimension()
    else:
        dim = request.dimension
    coll = await svc.create(
        name=request.collection_name,
        description=request.description or f"Векторная база {request.collection_name}",
        dimension=dim,
        recreate=request.recreate,
    )
    return {
        "status": "success",
        "message": f"Коллекция '{request.collection_name}' создана",
        "collection_name": coll.name,
        "dimension": dim,
    }


@router.post("/upload_batch")
async def upload_batch(
    collection_name: str,
    points: list[dict[str, Any]],
    qdrant=Depends(get_qdrant),
) -> dict:
    """Прямая загрузка батча точек (публичный, для обратной совместимости)."""
    qpoints = [
        qm.PointStruct(id=p["id"], vector=p["vector"], payload=p.get("payload", {}))
        for p in points
    ]
    qdrant.upsert(collection_name=collection_name, points=qpoints)
    return {"status": "success", "uploaded": len(points)}
