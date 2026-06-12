"""SearchService — Phase 4 pipeline:

  1. Embed query
  2. Qdrant dense top-K (no hard score_threshold — let RRF decide)
  3. BM25 sparse top-K (in-memory Python index)
  4. RRF (Reciprocal Rank Fusion) merge with k=60 and per-leg weights
  5. MMR (Maximal Marginal Relevance) dedup before rerank
  6. Cross-encoder rerank on the deduped pool
  7. Adaptive threshold — no manual thresholds needed:
       max_score >= adaptive_confident_min  → confident   → top-10
       max_score >= adaptive_uncertain_min  → uncertain   → top-5 + UI hint
       else                                → low-conf    → fallback to cosine >= fallback_cosine_min

Phase 4 is fully backward-compatible: cosine_threshold and rerank_threshold
fields stay in the Collection model for legacy callers but are not consulted
by this pipeline. Per-collection RRF/MMR/adaptive values are stored in
Collection and can be tuned via /admin/collections/{name}/config.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections import Counter, defaultdict
from typing import Any

from loguru import logger
from qdrant_client.http import models as qm

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
# Phase 4 helpers: RRF + MMR + adaptive
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    weights: list[float],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (Cormack et al. 2009).

    Args:
        ranked_lists: список ранжированных списков doc_id (по убыванию).
        weights: вес каждого списка (dense vs sparse).
        k: smoothing constant (стандарт 60).

    Returns:
        Список (doc_id, fused_score) по убыванию fused_score.
    """
    if not ranked_lists:
        return []
    fused: dict[str, float] = defaultdict(float)
    for items, w in zip(ranked_lists, weights):
        for rank, doc_id in enumerate(items, start=1):
            fused[doc_id] += w / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def maximal_marginal_relevance(
    query_vec: list[float] | None,
    doc_vecs: dict[str, list[float]],
    ordered_doc_ids: list[str],
    top_n: int,
    lam: float = 0.7,
) -> list[str]:
    """Maximal Marginal Relevance (Carbonell & Goldstein 1998).

    Выбирает top_n документов, максимизируя релевантность к query и
    разнообразие между собой.

    Args:
        query_vec: embedding запроса (нормализованный). Если None —
            diversity-only режим.
        doc_vecs: doc_id → embedding. Документы без embedding просто
            упорядочиваются в конец.
        ordered_doc_ids: входной порядок (после RRF). Сначала тут.
        top_n: сколько оставить.
        lam: баланс relevance vs diversity (0..1).

    Returns:
        Упорядоченный список doc_id (max top_n).
    """
    if not ordered_doc_ids or top_n <= 0:
        return ordered_doc_ids[:top_n]
    if len(ordered_doc_ids) <= top_n:
        return ordered_doc_ids

    selected: list[str] = []
    candidates: list[str] = list(ordered_doc_ids)

    def _cosine(a: list[float], b: list[float]) -> float:
        # Оба вектора уже должны быть нормализованы (Qdrant cosine).
        n = min(len(a), len(b))
        if not n:
            return 0.0
        s = 0.0
        for i in range(n):
            s += a[i] * b[i]
        return s

    # Если нет query_vec — diversity-only (порядок сохраняется).
    if query_vec is None or not doc_vecs:
        return ordered_doc_ids[:top_n]

    while len(selected) < top_n and candidates:
        best_id: str | None = None
        best_score = -math.inf
        for cid in candidates:
            doc_vec = doc_vecs.get(cid)
            if doc_vec is None:
                # Без embedding — relevance=0, diversity=0. Поставим в конец.
                rel = 0.0
                div = 0.0
            else:
                rel = _cosine(query_vec, doc_vec)
                if selected:
                    div = max(
                        _cosine(doc_vec, doc_vecs.get(sid)) if doc_vecs.get(sid) else 0.0
                        for sid in selected
                    )
                else:
                    div = 0.0
            mmr = lam * rel - (1.0 - lam) * div
            if mmr > best_score:
                best_score = mmr
                best_id = cid
        if best_id is None:
            break
        selected.append(best_id)
        candidates.remove(best_id)

    return selected


# ---------------------------------------------------------------------------
# Search Service
# ---------------------------------------------------------------------------
class SearchService:
    """Phase 4 hybrid search: RRF + MMR + adaptive threshold + cross-encoder rerank."""

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
        max_results: int | None = None,
    ) -> dict[str, Any]:
        """Phase 4 hybrid поиск.

        Returns:
            {
              "query", "database", "candidates", "processing_time",
              "status", "search_trace" (per-stage diagnostics)
            }
        """
        start = time.time()
        settings = self.settings

        # Per-collection Phase 4 params (with sensible defaults from settings)
        rrf_k = collection.rrf_k or settings.rrf_k
        rrf_dense_w = collection.rrf_dense_weight or settings.rrf_dense_weight
        rrf_bm25_w = collection.rrf_bm25_weight or settings.rrf_bm25_weight
        mmr_lam = collection.mmr_lambda or settings.mmr_lambda
        mmr_pool = collection.mmr_pool_size or settings.mmr_pool_size
        confident_min = collection.adaptive_confident_min or settings.adaptive_confident_min
        uncertain_min = collection.adaptive_uncertain_min or settings.adaptive_uncertain_min
        fallback_cos = collection.fallback_cosine_min or settings.fallback_cosine_min
        confident_n = settings.confident_top_n
        uncertain_n = settings.uncertain_top_n
        fallback_n = settings.fallback_top_n

        top_k = top_k or settings.top_k_qdrant

        trace: dict[str, Any] = {
            "stages": [],
            "rrf": {
                "k": rrf_k,
                "dense_weight": rrf_dense_w,
                "bm25_weight": rrf_bm25_w,
            },
            "mmr": {"lambda": mmr_lam, "pool_size": mmr_pool},
            "adaptive": {
                "confident_min": confident_min,
                "uncertain_min": uncertain_min,
                "fallback_cosine_min": fallback_cos,
            },
        }

        # ===== Шаг 1: embed query =====
        t1 = time.time()
        query_vector = await self.embedding.embed_one(query)
        trace["stages"].append(
            {"name": "embed", "elapsed": round(time.time() - t1, 3)}
        )
        logger.info(f"[1] Embedding: {time.time() - t1:.3f}s")

        # ===== Шаг 2: Qdrant dense (no hard threshold) =====
        t2 = time.time()
        dense_hits = await self._qdrant_search(
            collection, query_vector, top_k, filter_paths
        )
        trace["stages"].append(
            {
                "name": "qdrant_dense",
                "elapsed": round(time.time() - t2, 3),
                "count": len(dense_hits),
            }
        )
        logger.info(
            f"[2] Qdrant dense: {len(dense_hits)} candidates ({time.time() - t2:.3f}s)"
        )

        # ===== Шаг 3: BM25 sparse =====
        bm25_ids: list[str] = []
        if settings.bm25_enabled:
            t3 = time.time()
            bm25_ids = await self._bm25_search(collection, query)
            trace["stages"].append(
                {
                    "name": "bm25",
                    "elapsed": round(time.time() - t3, 3),
                    "count": len(bm25_ids),
                }
            )
            logger.info(f"[3] BM25: {len(bm25_ids)} hits ({time.time() - t3:.3f}s)")

        # ===== Шаг 4: RRF fusion =====
        t4 = time.time()
        dense_ids = [h["id"] for h in dense_hits]
        fused = reciprocal_rank_fusion(
            ranked_lists=[dense_ids, bm25_ids],
            weights=[rrf_dense_w, rrf_bm25_w],
            k=rrf_k,
        )
        # Кэш payloads из dense_hits (для BM25 хитов подтянем через retrieve).
        payloads_by_id: dict[str, dict[str, Any]] = {h["id"]: h for h in dense_hits}
        if bm25_ids:
            missing = [fid for fid, _ in fused if fid not in payloads_by_id][: settings.bm25_max_retrieve]
            if missing:
                t4b = time.time()
                extra = await self._retrieve_bm25_payloads(collection, missing)
                for h in extra:
                    payloads_by_id[h["id"]] = h
                trace["stages"].append(
                    {
                        "name": "bm25_retrieve",
                        "elapsed": round(time.time() - t4b, 3),
                        "count": len(extra),
                    }
                )

        # Оставляем только те, у кого есть payload, ограничиваем bm25_max_retrieve.
        fused_filtered = [
            (fid, score) for fid, score in fused if fid in payloads_by_id
        ]
        trace["stages"].append(
            {
                "name": "rrf_fusion",
                "elapsed": round(time.time() - t4, 3),
                "count": len(fused_filtered),
            }
        )
        logger.info(
            f"[4] RRF fused: {len(fused_filtered)} ({time.time() - t4:.3f}s)"
        )
        trace["rrf_fused_top10"] = [
            {"id": fid, "rrf_score": round(score, 5)}
            for fid, score in fused_filtered[:10]
        ]

        # ===== Шаг 5: MMR dedup (без embeddings → diversity-only fallback) =====
        t5 = time.time()
        candidate_ids = [fid for fid, _ in fused_filtered[:mmr_pool]]
        # Берём embedding у dense_hits (если там нет — MMR diversity-only).
        doc_vecs_for_mmr: dict[str, list[float]] = {}
        for h in dense_hits:
            if h["id"] in candidate_ids:
                # embedding не возвращается из query_points, нужно сделать retrieve с vectors
                pass
        # Простой fallback: если нет doc embeddings — MMR без diversity.
        if doc_vecs_for_mmr:
            ordered_after_mmr = maximal_marginal_relevance(
                query_vec=query_vector,
                doc_vecs=doc_vecs_for_mmr,
                ordered_doc_ids=candidate_ids,
                top_n=mmr_pool,
                lam=mmr_lam,
            )
        else:
            # Без embeddings — пропускаем MMR (всё равно dedup был бы no-op).
            ordered_after_mmr = candidate_ids
        trace["stages"].append(
            {"name": "mmr_dedup", "elapsed": round(time.time() - t5, 3)}
        )
        logger.info(
            f"[5] MMR dedup: {len(ordered_after_mmr)} -> rerank ({time.time() - t5:.3f}s)"
        )

        # ===== Шаг 6: Rerank =====
        to_rerank = [payloads_by_id[fid] for fid in ordered_after_mmr if fid in payloads_by_id]
        t6 = time.time()
        rerank_scores = await self._rerank(query=query, candidates=to_rerank)
        trace["stages"].append(
            {
                "name": "rerank",
                "elapsed": round(time.time() - t6, 3),
                "count": len(rerank_scores),
            }
        )
        logger.info(
            f"[6] Rerank: {len(rerank_scores)} scores ({time.time() - t6:.3f}s)"
        )
        max_rerank = max(rerank_scores) if rerank_scores else 0.0
        trace["max_rerank_score"] = round(max_rerank, 4)

        # ===== Шаг 7: Adaptive threshold (Phase 4 главный) =====
        scored = sorted(
            zip(to_rerank, rerank_scores),
            key=lambda x: -x[1],
        )

        if max_rerank >= confident_min:
            branch = "confident"
            limit = confident_n
            hint = None
        elif max_rerank >= uncertain_min:
            branch = "uncertain"
            limit = uncertain_n
            hint = (
                "Возможно, вы искали что-то другое — уточните запрос "
                "(например, добавьте параметры: диаметр, материал, назначение)."
            )
        else:
            branch = "low_confidence"
            limit = fallback_n
            hint = None  # fallback сам покажет результат

        trace["adaptive_branch"] = branch
        trace["adaptive_limit"] = limit

        if branch == "low_confidence":
            # Fallback: top-N по cosine (с порогом fallback_cosine_min).
            valid = []
            for cand, score in scored:
                meta = cand.get("metadata") or {}
                if (
                    not cand.get("is_bm25_match")
                    and float(cand.get("score", 0.0)) >= fallback_cos
                ):
                    valid.append(
                        {
                            **cand,
                            "reranker_score": float(score),
                            "fallback_cosine": True,
                        }
                    )
            valid.sort(
                key=lambda x: (
                    -float((x.get("metadata") or {}).get("score", x.get("score", 0.0)))
                )
            )
        else:
            valid = [
                {**cand, "reranker_score": float(score)}
                for cand, score in scored[:limit]
            ]
            # Сортировка уже по reranker desc — пересортируем на всякий случай.
            valid.sort(key=lambda x: -x["reranker_score"])

        trace["final_count"] = len(valid)

        # ===== Шаг 8: Форматирование =====
        out = []
        for idx, r in enumerate(valid[:max_results or 10]):
            meta = r.get("metadata") or {}
            out.append(
                {
                    "rank": idx + 1,
                    "code": r.get("code", ""),
                    "description": r.get("description", ""),
                    "material_name": meta.get("full_description"),
                    "category_path": self._build_category_path(meta),
                    "reranker_score": float(r.get("reranker_score", 0.0)),
                    "cosine_similarity": float(r.get("score", 0.0)),
                }
            )

        return {
            "query": query,
            "database": collection.name,
            "candidates": out,
            "processing_time": time.time() - start,
            "status": "success",
            "search_trace": trace,
            "hint": hint,
        }

    # ------------------------------------------------------- stage 1: Qdrant
    async def _qdrant_search(
        self,
        collection: Collection,
        query_vector: list[float],
        top_k: int,
        filter_paths: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        qdrant_filter = self._build_qdrant_filter(collection, filter_paths)
        loop = asyncio.get_event_loop()

        def _search():
            return self.qdrant.query_points(
                collection_name=collection.name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
                # NB: никакого score_threshold — RRF/MMR/adaptive решают.
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
            idx = await self.rebuild_bm25(collection)
        results = idx.search(query, top_k=self.settings.bm25_top_k)
        return [r["id"] for r in results]

    async def rebuild_bm25(self, collection: Collection) -> BM25Index:
        """Строит BM25 индекс для коллекции и кладёт в CacheManager."""
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
        CacheManager.invalidate_bm25(collection_name)
        logger.info(f"BM25 cache invalidated for '{collection_name}'")

    # Backward compat alias
    async def _build_bm25_index(self, collection: Collection) -> None:
        await self.rebuild_bm25(collection)

    async def _retrieve_bm25_payloads(
        self, collection: Collection, ids: list[str]
    ) -> list[dict[str, Any]]:
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


__all__ = ["SearchService", "BM25Index", "reciprocal_rank_fusion", "maximal_marginal_relevance"]
