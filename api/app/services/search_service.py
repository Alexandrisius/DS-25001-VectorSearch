"""SearchService — 2-stage retrieval: Qdrant (vector) + OpenRouter (rerank) + BM25 hybrid."""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from typing import Any

from loguru import logger
from qdrant_client.http import models as qm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.qdrant import get_qdrant_client
from app.models.collection import Collection
from app.services.cache_manager import CacheManager
from app.services.embedding_service import EmbeddingService
from app.services.rerank_service import RerankService


# ---------------------------------------------------------------------------
# BM25 in-memory
# ---------------------------------------------------------------------------
class BM25Index:
    """Простой in-memory BM25 индекс для гибридного поиска."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_len: dict[str, int] = {}
        self.avgdl: float = 0.0
        self.corpus_size: int = 0
        self.index: dict[str, dict[str, int]] = defaultdict(dict)
        self.idf: dict[str, float] = {}

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        if not text:
            return []
        return re.findall(r"(?u)\b\w[\w-]*\b", text.lower())

    def fit(self, corpus: dict[str, str]) -> None:
        self.doc_len = {}
        self.index = defaultdict(dict)
        self.corpus_size = len(corpus)
        total_len = 0
        for doc_id, text in corpus.items():
            tokens = self._tokenize(text)
            self.doc_len[doc_id] = len(tokens)
            total_len += len(tokens)
            counts = Counter(tokens)
            for token, count in counts.items():
                self.index[token][doc_id] = count
        self.avgdl = total_len / self.corpus_size if self.corpus_size else 0
        self._compute_idf()

    def _compute_idf(self) -> None:
        self.idf = {}
        for token, doc_map in self.index.items():
            n_q = len(doc_map)
            self.idf[token] = max(0.0, math.log(1 + (self.corpus_size - n_q + 0.5) / (n_q + 0.5)))

    def search(self, query: str, top_k: int = 200) -> list[dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens or not self.corpus_size:
            return []
        scores: dict[str, float] = defaultdict(float)
        for token in tokens:
            if token not in self.index:
                continue
            idf = self.idf[token]
            for doc_id, freq in self.index[token].items():
                doc_len = self.doc_len[doc_id]
                num = freq * (self.k1 + 1)
                den = freq + self.k1 * (1 - self.b + self.b * (doc_len / self.avgdl))
                scores[doc_id] += idf * (num / den)
        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{"id": doc_id, "score": score} for doc_id, score in sorted_docs]


# ---------------------------------------------------------------------------
# Search Service
# ---------------------------------------------------------------------------
class SearchService:
    """Главный сервис поиска: 2-stage (vector + rerank) с поддержкой BM25 hybrid."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        rerank_service: RerankService,
    ) -> None:
        self.session = session
        self.embedding = embedding_service
        self.rerank = rerank_service
        self.settings = get_settings()
        self.qdrant = get_qdrant_client()

    # ----------------------------------------------------------- public
    async def search(
        self,
        collection: Collection,
        query: str,
        *,
        filter_paths: list[dict[str, Any]] | None = None,
        top_k: int | None = None,
        max_for_rerank: int | None = None,
        max_results: int | None = None,
    ) -> dict[str, Any]:
        """2-stage + hybrid поиск.

        Returns:
            {"query", "database", "candidates", "processing_time", "status"}.
        """
        start = time.time()
        settings = self.settings

        top_k = top_k or settings.top_k_qdrant
        max_for_rerank = max_for_rerank or settings.max_for_rerank
        max_results = max_results or settings.max_results

        # Шаг 1: embed query
        t1 = time.time()
        query_vector = await self.embedding.embed_one(query)
        logger.info(f"[1] Embedding: {time.time() - t1:.3f}s")

        # Шаг 2: Qdrant ANN
        t2 = time.time()
        candidates = await self._qdrant_search(
            collection, query_vector, top_k, filter_paths
        )
        logger.info(f"[2] Qdrant: {len(candidates)} candidates ({time.time() - t2:.3f}s)")

        # Шаг 3 (опц): BM25 hybrid
        if settings.bm25_enabled:
            t3 = time.time()
            bm25_ids = await self._bm25_search(collection, query)
            logger.info(f"[3] BM25: {len(bm25_ids)} hits ({time.time() - t3:.3f}s)")

            if bm25_ids:
                t4 = time.time()
                extra = await self._retrieve_bm25_payloads(collection, bm25_ids)
                logger.info(f"[4] BM25 retrieve: {len(extra)} payloads ({time.time() - t4:.3f}s)")
                candidates.extend(extra)

        # Шаг 4: Подготовить для rerank (interleave dense + bm25, лимит)
        # Cohere rerank sweet spot: 30-50 docs. Делаем 30 dense + 20 bm25 = 50 max.
        dense_part = [c for c in candidates if not c.get("is_bm25_match")]
        bm25_part = [c for c in candidates if c.get("is_bm25_match")]

        rerank_limit = settings.hybrid_rerank_limit
        max_for_rerank = settings.max_for_rerank
        if len(candidates) <= rerank_limit:
            to_rerank = candidates[:max_for_rerank]
        else:
            dense_n = min(max_for_rerank - 20, len(dense_part))
            bm25_n = min(20, len(bm25_part))
            to_rerank = dense_part[:dense_n] + bm25_part[:bm25_n]

        # Шаг 5: Rerank
        t5 = time.time()
        rerank_scores = await self._rerank(
            query=query,
            candidates=to_rerank,
        )
        logger.info(f"[5] Rerank: {len(rerank_scores)} scores ({time.time() - t5:.3f}s)")

        # Шаг 6: Фильтр по rerank_threshold
        valid = []
        for cand, score in zip(to_rerank, rerank_scores):
            if score >= collection.rerank_threshold:
                valid.append({**cand, "reranker_score": float(score)})
        valid.sort(key=lambda x: x["reranker_score"], reverse=True)

        # Шаг 7: Форматирование
        out = []
        for idx, r in enumerate(valid[:max_results]):
            out.append(
                {
                    "rank": idx + 1,
                    "code": r.get("code", ""),
                    "description": r.get("description", ""),
                    "material_name": (r.get("metadata") or {}).get("full_description"),
                    "category_path": self._build_category_path(r.get("metadata") or {}),
                    "reranker_score": r["reranker_score"],
                    "cosine_similarity": float(r.get("score", 0.0)),
                }
            )

        return {
            "query": query,
            "database": collection.name,
            "candidates": out,
            "processing_time": time.time() - start,
            "status": "success",
        }

    # ------------------------------------------------------- stage 1: Qdrant
    async def _qdrant_search(
        self,
        collection: Collection,
        query_vector: list[float],
        top_k: int,
        filter_paths: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        # Построить фильтр
        qdrant_filter = self._build_qdrant_filter(collection, filter_paths)
        loop = asyncio.get_event_loop()

        def _search():
            return self.qdrant.query_points(
                collection_name=collection.name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
                score_threshold=collection.cosine_threshold,
                query_filter=qdrant_filter,
            ).points

        points = await loop.run_in_executor(None, _search)
        results: list[dict[str, Any]] = []
        for hit in points:
            results.append(
                {
                    "id": str(hit.id),
                    "score": float(hit.score),
                    "code": (hit.payload or {}).get("code", ""),
                    "description": (hit.payload or {}).get("description", ""),
                    "metadata": hit.payload or {},
                }
            )
        return results

    def _build_qdrant_filter(
        self, collection: Collection, filter_paths: list[dict[str, Any]] | None
    ) -> qm.Filter:
        """Строим Qdrant фильтр: exclude folders + (multi) path filter."""
        exclude_folders = qm.FieldCondition(
            key="is_folder", match=qm.MatchValue(value=True)
        )

        if not filter_paths:
            return qm.Filter(must_not=[exclude_folders])

        # Множественный OR фильтр
        if len(filter_paths) == 1:
            conditions = self._path_conditions(filter_paths[0]["path"])
            return qm.Filter(must=conditions, must_not=[exclude_folders])

        category_filters = []
        for fp in filter_paths:
            conds = self._path_conditions(fp["path"])
            if conds:
                category_filters.append(qm.Filter(must=conds))
        return qm.Filter(should=category_filters, must_not=[exclude_folders])

    @staticmethod
    def _path_conditions(path: str) -> list[qm.FieldCondition]:
        parts = [p.strip() for p in path.split("→") if p.strip()]
        return [
            qm.FieldCondition(
                key=f"path_level_{i + 1}",
                match=qm.MatchValue(value=part),
            )
            for i, part in enumerate(parts)
        ]

    # ----------------------------------------------------- stage 1.5: BM25
    async def _bm25_search(self, collection: Collection, query: str) -> list[str]:
        idx = CacheManager.get_bm25(collection.name)
        if idx is None:
            # Cache miss (после invalidation или cold start без warmup)
            idx = await self.rebuild_bm25(collection)
        results = idx.search(query, top_k=self.settings.bm25_top_k)
        return [r["id"] for r in results]

    async def rebuild_bm25(self, collection: Collection) -> BM25Index:
        """Строит BM25 индекс для коллекции и кладёт в CacheManager.

        Вызывается:
        - Из lifespan (eager warmup при старте)
        - Из _bm25_search (lazy fallback если warmup не отработал)
        - Никогда напрямую из hot path: используй invalidate_bm25() для сброса
        """
        logger.info(f"Building BM25 index for {collection.name}…")
        corpus: dict[str, str] = {}
        offset = None
        loop = asyncio.get_event_loop()

        def _scroll():
            return self.qdrant.scroll(
                collection_name=collection.name,
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

        while True:
            points, offset = await loop.run_in_executor(None, _scroll)
            for p in points:
                payload = p.payload or {}
                full = payload.get("full_description") or payload.get("description", "")
                code = payload.get("code", "")
                text = f"{code} {full}".strip()
                if text:
                    corpus[str(p.id)] = text
            if offset is None:
                break
        idx = BM25Index()
        idx.fit(corpus)
        CacheManager.set_bm25(collection.name, idx)
        logger.info(f"BM25 built: {len(corpus)} docs")
        return idx

    def invalidate_bm25(self, collection_name: str) -> None:
        """Сбрасывает BM25 индекс коллекции (вызывать при обновлении данных)."""
        CacheManager.invalidate_bm25(collection_name)
        logger.info(f"BM25 cache invalidated for '{collection_name}'")

    # Backward compat alias (использовался раньше)
    async def _build_bm25_index(self, collection: Collection) -> None:
        await self.rebuild_bm25(collection)

    async def _retrieve_bm25_payloads(
        self, collection: Collection, ids: list[str]
    ) -> list[dict[str, Any]]:
        # Уникальные + в пределах лимита
        unique = list(dict.fromkeys(ids))[: self.settings.bm25_max_retrieve]
        if not unique:
            return []
        loop = asyncio.get_event_loop()

        def _retrieve():
            return self.qdrant.retrieve(
                collection_name=collection.name,
                ids=unique,
                with_payload=True,
                with_vectors=False,
            )

        points = await loop.run_in_executor(None, _retrieve)
        results: list[dict[str, Any]] = []
        for p in points:
            results.append(
                {
                    "id": str(p.id),
                    "score": 0.0,
                    "code": (p.payload or {}).get("code", ""),
                    "description": (p.payload or {}).get("description", ""),
                    "metadata": p.payload or {},
                    "is_bm25_match": True,
                }
            )
        return results

    # ---------------------------------------------------------- stage 2: rerank
    async def _rerank(
        self, query: str, candidates: list[dict[str, Any]]
    ) -> list[float]:
        if not candidates:
            return []
        # Текст для реранкинга: full_description (приоритет) > description
        pairs_docs: list[str] = []
        for c in candidates:
            meta = c.get("metadata") or {}
            txt = meta.get("full_description") or c.get("description") or ""
            pairs_docs.append(txt)
        return await self.rerank.rerank(query=query, documents=pairs_docs)

    # ------------------------------------------------------------- utils
    @staticmethod
    def _build_category_path(meta: dict[str, Any]) -> str | None:
        depth = meta.get("path_depth", 0)
        if not depth:
            return None
        parts: list[str] = []
        for i in range(1, depth + 1):
            v = meta.get(f"path_level_{i}")
            if v:
                parts.append(v)
            else:
                break
        return " → ".join(parts) if parts else None


__all__ = ["SearchService", "BM25Index"]
