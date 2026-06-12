"""Search API — /match (публичный, главный endpoint поиска)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import DBSession
from app.schemas.material import (
    CandidateResult,
    MatchRequest,
    MatchResponse,
)
from app.services.collection_service import CollectionService
from app.services.search_service import SearchService
from app.di import get_search_service

router = APIRouter(tags=["search"])


@router.post("/match", response_model=MatchResponse)
async def match(
    request: MatchRequest,
    session: DBSession,
    search: SearchService = Depends(get_search_service),
) -> MatchResponse:
    """2-stage retrieval: Qdrant (vector) + OpenRouter (rerank)."""
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Текст не может быть пустым")

    coll_svc = CollectionService(session)
    coll = await coll_svc.get_current_active(request.database)
    if not coll:
        raise HTTPException(
            status_code=404,
            detail=f"Коллекция '{request.database or 'default'}' не найдена",
        )

    # Преобразование filter_paths (если есть)
    filter_paths = None
    if request.filter_paths:
        filter_paths = [{"path": fp.path, "level": fp.level} for fp in request.filter_paths]
    elif request.filter_path:
        filter_paths = [{"path": request.filter_path, "level": request.filter_level}]

    result = await search.search(
        collection=coll,
        query=request.text,
        filter_paths=filter_paths,
        max_results=request.max_results,
    )
    return MatchResponse(**result)


@router.post("/set_database")
async def set_database(database_name: str, session: DBSession) -> dict:
    """Установить активную коллекцию (для совместимости с UI)."""
    from sqlalchemy import update
    from app.models.collection import Collection
    # В v2 — нет понятия current, UI сам выбирает.
    coll = await CollectionService(session).get_by_name(database_name)
    if not coll:
        raise HTTPException(status_code=404, detail=f"Коллекция '{database_name}' не найдена")
    return {"status": "success", "message": f"Активная коллекция: {database_name}"}


@router.get("/databases")
async def list_databases(session: DBSession) -> dict:
    """Список visible коллекций (публичный, для UI поиска).

    Использует list_visible_fast() (без selectinload) + stored counter
    Collection.materials_count — иначе SELECT COUNT для 142k записей
    даёт 6+ сек лаг при каждом открытии главной страницы.
    """
    svc = CollectionService(session)
    visible = await svc.list_visible_fast()
    current = await svc.get_current_active(None)
    return {
        "databases": [
            {
                "name": c.name,
                "description": c.description or c.name,
                "record_count": c.materials_count or 0,
                "dimension": c.dimension,
                "thresholds": {
                    "cosine": c.cosine_threshold,
                    "rerank": c.rerank_threshold,
                },
                "phase4": {
                    "rrf_k": c.rrf_k,
                    "rrf_dense_weight": c.rrf_dense_weight,
                    "rrf_bm25_weight": c.rrf_bm25_weight,
                    "mmr_lambda": c.mmr_lambda,
                    "mmr_pool_size": c.mmr_pool_size,
                    "adaptive_confident_min": c.adaptive_confident_min,
                    "adaptive_uncertain_min": c.adaptive_uncertain_min,
                    "fallback_cosine_min": c.fallback_cosine_min,
                },
                "last_updated": c.last_updated.isoformat() if c.last_updated else "",
            }
            for c in visible
        ],
        "current_database": current.name if current else None,
    }
