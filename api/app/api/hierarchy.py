"""Hierarchy API — /hierarchy/{db}/* (публичный)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.deps import DBSession
from app.schemas.hierarchy import (
    HierarchyChildrenResponse,
    HierarchyResponse,
    HierarchySearchRequest,
    HierarchySearchResponse,
)
from app.services.collection_service import CollectionService
from app.services.hierarchy_service import HierarchyService
from app.di import get_hierarchy_service

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


async def _resolve_coll(session, name: str):
    coll = await CollectionService(session).get_by_name(name)
    if not coll:
        raise HTTPException(status_code=404, detail=f"Коллекция '{name}' не найдена")
    return coll


@router.get("/{database_name}", response_model=HierarchyResponse)
async def get_hierarchy(
    database_name: str,
    max_depth: int = 10,
    session: DBSession = None,
    svc: HierarchyService = Depends(get_hierarchy_service),
) -> HierarchyResponse:
    coll = await _resolve_coll(session, database_name)
    result = await svc.get_tree(coll, max_depth=max_depth)
    return HierarchyResponse(**result)


@router.get("/{database_name}/children", response_model=HierarchyChildrenResponse)
async def get_children(
    database_name: str,
    parent_path: str = "",
    level: int = 1,
    session: DBSession = None,
    svc: HierarchyService = Depends(get_hierarchy_service),
) -> HierarchyChildrenResponse:
    coll = await _resolve_coll(session, database_name)
    parent_level = (
        parent_path.count("→") if parent_path else 0
    )
    result = await svc.get_children(coll, parent_path=parent_path, parent_level=parent_level)
    return HierarchyChildrenResponse(**result)


@router.post("/{database_name}/search", response_model=HierarchySearchResponse)
async def search_hierarchy(
    database_name: str,
    request: HierarchySearchRequest,
    session: DBSession = None,
    svc: HierarchyService = Depends(get_hierarchy_service),
) -> HierarchySearchResponse:
    coll = await _resolve_coll(session, database_name)
    result = await svc.search_categories(coll, request.text, top_k=request.top_k)
    return HierarchySearchResponse(**result)


@router.post("/{database_name}/invalidate")
async def invalidate(
    database_name: str,
    session: DBSession = None,
    svc: HierarchyService = Depends(get_hierarchy_service),
) -> dict:
    coll = await _resolve_coll(session, database_name)
    svc.invalidate_cache(coll.name)
    return {"status": "success", "message": f"Кэш '{database_name}' очищен"}
