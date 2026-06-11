"""HierarchyService — построение и поиск по иерархии категорий."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger
from qdrant_client.http import models as qm
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.qdrant import get_qdrant_client
from app.models.collection import Collection
from app.services.embedding_service import EmbeddingService
from app.services.rerank_service import RerankService


class HierarchyService:
    """Сервис иерархии: построение дерева + семантический поиск категорий."""

    CACHE_TTL = 300.0  # 5 минут

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        rerank_service: RerankService,
    ) -> None:
        self.session = session
        self.embedding = embedding_service
        self.rerank = rerank_service
        self.qdrant = get_qdrant_client()
        self._tree_cache: dict[str, dict] = {}
        self._children_cache: dict[str, dict] = {}

    # -------------------------------------------------------- public api
    async def get_tree(
        self, collection: Collection, max_depth: int = 10
    ) -> dict[str, Any]:
        """Полное дерево иерархии (с кэшем 5 мин)."""
        cached = self._tree_cache.get(collection.name)
        if cached and (time.time() - cached["ts"]) < self.CACHE_TTL:
            return {
                "tree": cached["tree"],
                "total_categories": cached["stats"]["total_categories"],
                "total_items": cached["stats"]["total_items"],
                "max_depth": cached["stats"]["max_depth"],
                "cached": True,
                "cache_age": int(time.time() - cached["ts"]),
            }

        start = time.time()
        tree_data = await self._build_tree(collection, max_depth)
        self._tree_cache[collection.name] = {
            "tree": tree_data["tree"],
            "stats": tree_data["stats"],
            "ts": time.time(),
        }
        elapsed = time.time() - start
        logger.info(f"✅ Tree built in {elapsed:.2f}s ({tree_data['stats']['total_categories']} categories)")

        return {
            "tree": tree_data["tree"],
            "total_categories": tree_data["stats"]["total_categories"],
            "total_items": tree_data["stats"]["total_items"],
            "max_depth": tree_data["stats"]["max_depth"],
            "cached": False,
            "build_time": elapsed,
        }

    async def get_children(
        self, collection: Collection, parent_path: str = "", parent_level: int = 0
    ) -> dict[str, Any]:
        """Ленивая загрузка прямых детей."""
        cache_key = f"{collection.name}::{parent_level}::{parent_path}"
        cached = self._children_cache.get(cache_key)
        if cached and (time.time() - cached["ts"]) < self.CACHE_TTL:
            return {
                "children": cached["children"],
                "materials": cached.get("materials", []),
                "parent_path": parent_path,
                "total": cached["total"],
                "cached": True,
            }

        parent_parts = [p.strip() for p in parent_path.split("→") if p.strip()] if parent_path else []
        child_level = parent_level + 1
        child_field = f"path_level_{child_level}"

        # Условия для родительского пути
        filter_conditions = [
            qm.FieldCondition(
                key=f"path_level_{i + 1}",
                match=qm.MatchValue(value=part),
            )
            for i, part in enumerate(parent_parts)
        ]

        # В Qdrant filter всегда must_not: is_folder=false (для children),
        # но тут нам нужны как папки так и материалы, поэтому не фильтруем.

        loop = asyncio.get_event_loop()

        def _scroll():
            offset = None
            children_map: dict[str, dict[str, Any]] = {}
            materials: list[dict[str, Any]] = []
            while True:
                points, offset = self.qdrant.scroll(
                    collection_name=collection.name,
                    limit=2000,
                    offset=offset,
                    with_payload=[
                        f"path_level_{i}" for i in range(1, child_level + 2)
                    ] + ["code", "path_depth", "full_description", "is_folder"],
                    with_vectors=False,
                    scroll_filter=qm.Filter(must=filter_conditions) if filter_conditions else None,
                )
                for p in points:
                    payload = p.payload or {}
                    # Проверяем соответствие parent
                    if any(
                        payload.get(f"path_level_{i + 1}") != part
                        for i, part in enumerate(parent_parts)
                    ):
                        continue
                    child_value = payload.get(child_field)
                    depth = payload.get("path_depth", 0)
                    code = payload.get("code", "")
                    full = payload.get("full_description", "")
                    is_folder = payload.get("is_folder", False)

                    if child_value and not is_folder:
                        if child_value not in children_map:
                            children_map[child_value] = {
                                "name": child_value,
                                "count": 0,
                                "has_children": False,
                                "materials": [],
                                "codes": [],
                            }
                        children_map[child_value]["count"] += 1
                        if payload.get(f"path_level_{child_level + 1}"):
                            children_map[child_value]["has_children"] = True
                        if len(children_map[child_value]["materials"]) < 5 and full:
                            children_map[child_value]["materials"].append(
                                {"code": code, "name": full}
                            )
                    elif depth == parent_level and full and not is_folder:
                        if len(materials) < 50:
                            materials.append(
                                {"code": code, "name": full, "is_material": True}
                            )
                if offset is None:
                    break
            return children_map, materials

        children_map, materials = await loop.run_in_executor(None, _scroll)

        # Форматируем детей
        children: list[dict[str, Any]] = []
        for name, data in children_map.items():
            child_path = (f"{parent_path} → {name}" if parent_path else name) if parent_path else name
            child = {
                "name": name,
                "path": f"{parent_path} → {name}" if parent_path else name,
                "level": child_level,
                "count": data["count"],
                "has_children": data["has_children"],
                "is_category": True,
            }
            if data["materials"] and not data["has_children"]:
                child["materials"] = data["materials"]
                child["has_materials"] = True
            children.append(child)
        children.sort(key=lambda x: x["name"])
        materials.sort(key=lambda x: x.get("name", ""))

        result = {
            "children": children,
            "materials": materials,
            "parent_path": parent_path,
            "total": len(children) + len(materials),
        }
        self._children_cache[cache_key] = {
            "children": children,
            "materials": materials,
            "total": result["total"],
            "ts": time.time(),
        }
        return result

    async def search_categories(
        self, collection: Collection, query: str, top_k: int = 10
    ) -> dict[str, Any]:
        """Семантический поиск по папкам (vector + rerank по leaf_name)."""
        query_vector = await self.embedding.embed_one(query)
        # cosine threshold для папок — мягче
        cosine_threshold = collection.cosine_threshold * 0.7

        loop = asyncio.get_event_loop()

        def _search():
            return self.qdrant.query_points(
                collection_name=collection.name,
                query=query_vector,
                limit=50,
                with_payload=True,
                with_vectors=False,
                score_threshold=cosine_threshold,
                query_filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="is_folder", match=qm.MatchValue(value=True)
                        )
                    ]
                ),
            ).points

        points = await loop.run_in_executor(None, _search)
        if not points:
            return {"categories": [], "query": query, "total_found": 0}

        # Подготовить для rerank
        cands = []
        for hit in points:
            payload = hit.payload or {}
            cands.append(
                {
                    "path": payload.get("full_path", payload.get("description", "")),
                    "name": payload.get("leaf_name", ""),
                    "level": payload.get("path_depth", 0),
                    "items_count": payload.get("items_count", 0),
                    "cosine_score": float(hit.score),
                    "metadata": payload,
                }
            )

        # Rerank по leaf_name
        if cands:
            scores = await self.rerank.rerank(
                query=query,
                documents=[c["name"].lower() for c in cands],
            )
            for i, c in enumerate(cands):
                c["rerank_score"] = float(scores[i]) if i < len(scores) else 0.0
            cands.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

        # Удалить metadata
        out = []
        for c in cands[:top_k]:
            out.append(
                {
                    "path": c["path"],
                    "name": c["name"],
                    "level": c["level"],
                    "items_count": c["items_count"],
                    "cosine_score": round(c["cosine_score"], 4),
                    "rerank_score": round(c.get("rerank_score", 0), 4),
                }
            )
        return {"categories": out, "query": query, "total_found": len(out)}

    # ---------------------------------------------------------- private
    async def _build_tree(
        self, collection: Collection, max_depth: int
    ) -> dict[str, Any]:
        """Построение дерева иерархии через scroll по всем записям."""
        categories: dict[tuple, dict[str, Any]] = {}
        materials_by_parent: dict[tuple, list[dict[str, Any]]] = {}
        total_items = 0
        max_found_depth = 0

        loop = asyncio.get_event_loop()

        def _scroll():
            offset = None
            local_cats: dict[tuple, dict[str, Any]] = {}
            local_mats: dict[tuple, list[dict[str, Any]]] = {}
            local_total = 0
            local_max_depth = 0
            while True:
                points, offset = self.qdrant.scroll(
                    collection_name=collection.name,
                    limit=2000,
                    offset=offset,
                    with_payload=[
                        f"path_level_{i}" for i in range(1, max_depth + 1)
                    ] + ["path_depth", "code", "full_description", "is_folder"],
                    with_vectors=False,
                )
                for p in points:
                    local_total += 1
                    payload = p.payload or {}
                    if payload.get("is_folder"):
                        continue
                    depth = payload.get("path_depth", 0)
                    code = payload.get("code", "")
                    full = payload.get("full_description", "")
                    local_max_depth = max(local_max_depth, depth)
                    parts: list[str] = []
                    for lvl in range(1, depth + 1):
                        v = payload.get(f"path_level_{lvl}")
                        if v:
                            parts.append(v)
                        else:
                            break
                    for i in range(len(parts)):
                        level = i + 1
                        cur = tuple(parts[:level])
                        par = tuple(parts[: i]) if i else ()
                        if cur not in local_cats:
                            local_cats[cur] = {
                                "name": parts[i],
                                "level": level,
                                "count": 0,
                                "parent": par,
                                "has_materials": False,
                            }
                        local_cats[cur]["count"] += 1
                    if full:
                        parent = tuple(parts)
                        local_mats.setdefault(parent, [])
                        if len(local_mats[parent]) < 5:
                            local_mats[parent].append({"code": code, "full_description": full})
                        if parent in local_cats:
                            local_cats[parent]["has_materials"] = True
                if offset is None:
                    break
            return local_cats, local_mats, local_total, local_max_depth

        categories, materials_by_parent, total_items, max_found_depth = await loop.run_in_executor(None, _scroll)

        # Build tree
        tree = self._build_tree_structure(categories, materials_by_parent, max_depth)
        return {
            "tree": tree,
            "stats": {
                "total_categories": len(categories),
                "total_items": total_items,
                "total_materials": sum(len(m) for m in materials_by_parent.values()),
                "max_depth": max_found_depth,
            },
        }

    def _build_tree_structure(
        self,
        categories: dict[tuple, dict[str, Any]],
        materials_by_parent: dict[tuple, list[dict[str, Any]]],
        max_depth: int,
    ) -> list[dict[str, Any]]:
        def _children(parent: tuple, level: int) -> list[dict[str, Any]]:
            if level > max_depth:
                return []
            out = []
            for path_tuple, data in categories.items():
                if data["parent"] != parent or data["level"] != level:
                    continue
                path_str = " → ".join(path_tuple) if path_tuple else ""
                node = {
                    "name": data["name"],
                    "path": path_str,
                    "level": data["level"],
                    "count": data["count"],
                    "is_category": True,
                    "has_materials": data["has_materials"],
                    "children": _children(path_tuple, level + 1),
                }
                if path_tuple in materials_by_parent and not node["children"]:
                    mats = materials_by_parent[path_tuple]
                    if mats:
                        node["materials"] = [
                            {"name": m["full_description"], "code": m["code"], "is_material": True}
                            for m in mats[:5]
                        ]
                        node["materials_count"] = len(materials_by_parent[path_tuple])
                out.append(node)
            out.sort(key=lambda x: x["name"])
            return out

        roots: list[dict[str, Any]] = []
        for path_tuple, data in categories.items():
            if data["level"] == 1:
                path_str = " → ".join(path_tuple)
                node = {
                    "name": data["name"],
                    "path": path_str,
                    "level": 1,
                    "count": data["count"],
                    "is_category": True,
                    "has_materials": data["has_materials"],
                    "children": _children(path_tuple, 2),
                }
                if path_tuple in materials_by_parent and not node["children"]:
                    mats = materials_by_parent[path_tuple]
                    if mats:
                        node["materials"] = [
                            {"name": m["full_description"], "code": m["code"], "is_material": True}
                            for m in mats[:5]
                        ]
                        node["materials_count"] = len(materials_by_parent[path_tuple])
                roots.append(node)
        roots.sort(key=lambda x: x["name"])
        return roots

    def invalidate_cache(self, collection_name: str | None = None) -> None:
        if collection_name:
            self._tree_cache.pop(collection_name, None)
            keys = [k for k in self._children_cache if k.startswith(f"{collection_name}::")]
            for k in keys:
                self._children_cache.pop(k, None)
        else:
            self._tree_cache.clear()
            self._children_cache.clear()


__all__ = ["HierarchyService"]
