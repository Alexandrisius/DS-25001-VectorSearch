"""SearchAnalyticsService — запись search_events + KPI/дашборд запросы.

Используется в двух контекстах:
1. /match → record() пишет строку (факт поиска с таймингами)
2. /admin/analytics/* → read-only методы для дашборда
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_event import SearchEvent
from app.models.feedback_event import FeedbackEvent
from app.utils.text import clean_text_for_json


class SearchAnalyticsService:
    """Сервис аналитики поиска."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # =====================================================================
    # WRITE
    # =====================================================================
    async def record(
        self,
        *,
        query: str,
        stages_ms: dict[str, int],
        candidates_count: int,
        branch: str | None,
        top_results: list[dict[str, Any]] | None,
        collection: str | None,
        filter_paths: list[dict[str, Any]] | None,
        request_id: str | None,
        session_id: str | None,
        user_ip: str | None,
        user_agent: str | None,
        model_embed: str | None,
        model_rerank: str | None,
        status: str = "success",
        error: str | None = None,
    ) -> SearchEvent:
        """Записать событие поиска в Postgres.

        stages_ms принимает ключи в формате search_service:
          embed, qdrant_dense, bm25, bm25_retrieve, rrf_fusion,
          mmr_dedup, rerank, total.

        Маппинг в типизированные колонки: qdrant_dense → qdrant_ms,
        rrf_fusion → rrf_ms, mmr_dedup → mmr_ms, bm25_retrieve
        суммируется в bm25_ms (как часть BM25-логики).
        """
        qdrant = stages_ms.get("qdrant_dense")
        bm25_total = (stages_ms.get("bm25") or 0) + (stages_ms.get("bm25_retrieve") or 0)
        rrf = stages_ms.get("rrf_fusion")
        mmr = stages_ms.get("mmr_dedup")
        evt = SearchEvent(
            request_id=request_id,
            session_id=session_id,
            user_ip=user_ip,
            user_agent=user_agent,
            query=clean_text_for_json(query)[:1000],
            collection=collection,
            filter_paths={"paths": filter_paths} if filter_paths else None,
            embed_ms=stages_ms.get("embed"),
            qdrant_ms=qdrant,
            bm25_ms=bm25_total or None,
            rrf_ms=rrf,
            mmr_ms=mmr,
            rerank_ms=stages_ms.get("rerank"),
            total_ms=stages_ms.get("total"),
            candidates_count=candidates_count,
            branch=branch,
            top_results={"items": top_results[:10]} if top_results else None,
            model_embed=model_embed,
            model_rerank=model_rerank,
            status=status,
            error=error,
        )
        self.session.add(evt)
        await self.session.flush()
        logger.debug(f"[search-analytics] recorded id={evt.id} query={query[:50]!r}")
        return evt

    # =====================================================================
    # READ — KPI для дашборда
    # =====================================================================
    async def kpi(self, hours: int = 24) -> dict[str, Any]:
        """KPI за последние N часов."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Суммарные счётчики
        totals_q = await self.session.execute(
            text(
                """
                SELECT
                    COUNT(*)                                            AS searches,
                    COUNT(DISTINCT session_id) FILTER (WHERE session_id IS NOT NULL)
                                                                        AS unique_sessions,
                    COUNT(DISTINCT user_ip)   FILTER (WHERE user_ip IS NOT NULL)
                                                                        AS unique_users,
                    SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END) AS zero_result,
                    ROUND(
                        100.0 * SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END)
                              / NULLIF(COUNT(*), 0), 2
                    )                                                   AS zero_result_pct,
                    ROUND(AVG(total_ms)::numeric, 0)                    AS avg_total_ms,
                    ROUND(percentile_cont(0.5)  WITHIN GROUP (ORDER BY total_ms))
                                                                        AS p50_total_ms,
                    ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms))
                                                                        AS p95_total_ms,
                    ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY rerank_ms))
                                                                        AS p95_rerank_ms,
                    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)   AS errors
                FROM search_events
                WHERE ts >= :since
                """
            ),
            {"since": since},
        )
        row = totals_q.mappings().one()

        # Сравнение с предыдущим окном (для дельт на UI)
        prev_since = since - timedelta(hours=hours)
        prev_q = await self.session.execute(
            text(
                """
                SELECT
                    COUNT(*)                                            AS searches,
                    ROUND(AVG(total_ms)::numeric, 0)                    AS avg_total_ms,
                    ROUND(
                        100.0 * SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END)
                              / NULLIF(COUNT(*), 0), 2
                    )                                                   AS zero_result_pct
                FROM search_events
                WHERE ts >= :prev_since AND ts < :since
                """
            ),
            {"prev_since": prev_since, "since": since},
        )
        prev = prev_q.mappings().one()

        return {
            "window_hours": hours,
            "searches": int(row["searches"] or 0),
            "unique_sessions": int(row["unique_sessions"] or 0),
            "unique_users": int(row["unique_users"] or 0),
            "zero_result": int(row["zero_result"] or 0),
            "zero_result_pct": float(row["zero_result_pct"] or 0),
            "avg_total_ms": int(row["avg_total_ms"] or 0),
            "p50_total_ms": int(row["p50_total_ms"] or 0),
            "p95_total_ms": int(row["p95_total_ms"] or 0),
            "p95_rerank_ms": int(row["p95_rerank_ms"] or 0),
            "errors": int(row["errors"] or 0),
            "prev": {
                "searches": int(prev["searches"] or 0),
                "avg_total_ms": int(prev["avg_total_ms"] or 0),
                "zero_result_pct": float(prev["zero_result_pct"] or 0),
            },
        }

    async def recent_searches(
        self, *, limit: int = 50, hours: int = 168
    ) -> list[dict[str, Any]]:
        """Последние N поисков (по умолчанию за неделю)."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        # Соединяем с feedback_events, чтобы видеть были ли копирования/дизлайки
        result = await self.session.execute(
            text(
                """
                SELECT
                    s.id,
                    s.ts,
                    s.user_ip,
                    s.session_id,
                    s.query,
                    s.collection,
                    s.candidates_count,
                    s.branch,
                    s.total_ms,
                    s.rerank_ms,
                    s.embed_ms,
                    s.qdrant_ms,
                    s.bm25_ms,
                    s.status,
                    s.top_results,
                    (SELECT COUNT(*) FROM feedback_events f
                       WHERE f.session_id = s.session_id
                         AND f.ts >= s.ts
                         AND f.ts <  s.ts + INTERVAL '10 minutes'
                         AND f.action = 'copy')                        AS copies_after,
                    (SELECT COUNT(*) FROM feedback_events f
                       WHERE f.session_id = s.session_id
                         AND f.ts >= s.ts
                         AND f.ts <  s.ts + INTERVAL '10 minutes'
                         AND f.action = 'dislike')                     AS dislikes_after
                FROM search_events s
                WHERE s.ts >= :since
                ORDER BY s.ts DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        rows = result.mappings().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            tr = r["top_results"] or {}
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"].isoformat() if r["ts"] else None,
                    "user_ip": r["user_ip"],
                    "session_id": r["session_id"],
                    "query": r["query"],
                    "collection": r["collection"],
                    "candidates_count": r["candidates_count"],
                    "branch": r["branch"],
                    "total_ms": r["total_ms"],
                    "rerank_ms": r["rerank_ms"],
                    "embed_ms": r["embed_ms"],
                    "qdrant_ms": r["qdrant_ms"],
                    "bm25_ms": r["bm25_ms"],
                    "status": r["status"],
                    "top_codes": [
                        item.get("code") for item in (tr.get("items") or [])[:3]
                    ],
                    "copies_after": int(r["copies_after"] or 0),
                    "dislikes_after": int(r["dislikes_after"] or 0),
                }
            )
        return out

    async def top_queries(
        self, *, limit: int = 30, days: int = 90
    ) -> list[dict[str, Any]]:
        """Самые частые запросы за период."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            text(
                """
                SELECT
                    query,
                    COUNT(*)                                       AS cnt,
                    COUNT(DISTINCT user_ip)                        AS unique_users,
                    ROUND(AVG(total_ms)::numeric, 0)               AS avg_total_ms,
                    ROUND(AVG(candidates_count)::numeric, 1)       AS avg_candidates,
                    SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END) AS zero_result_count,
                    MAX(ts)                                        AS last_seen
                FROM search_events
                WHERE ts >= :since AND status = 'success'
                GROUP BY query
                ORDER BY cnt DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]

    async def zero_result_queries(
        self, *, limit: int = 30, days: int = 90
    ) -> list[dict[str, Any]]:
        """Топ zero-result запросов (контент-гэпы базы)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            text(
                """
                SELECT
                    query,
                    COUNT(*)            AS cnt,
                    COUNT(DISTINCT user_ip) AS unique_users,
                    MAX(ts)             AS last_seen,
                    MIN(ts)             AS first_seen
                FROM search_events
                WHERE ts >= :since AND status = 'success' AND candidates_count = 0
                GROUP BY query
                ORDER BY cnt DESC
                LIMIT :limit
                """
            ),
            {"since": since, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]

    async def slow_searches(
        self, *, limit: int = 20, hours: int = 168, threshold_ms: int = 3000
    ) -> list[dict[str, Any]]:
        """Самые медленные поиски (для отладки реранкера/провайдера)."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.session.execute(
            text(
                """
                SELECT
                    id, ts, user_ip, query, collection,
                    total_ms, rerank_ms, embed_ms, qdrant_ms, bm25_ms,
                    branch, candidates_count, model_rerank
                FROM search_events
                WHERE ts >= :since AND status = 'success' AND total_ms >= :thr
                ORDER BY total_ms DESC
                LIMIT :limit
                """
            ),
            {"since": since, "thr": threshold_ms, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]

    async def user_timeline(
        self, *, user_ip: str, hours: int = 24
    ) -> dict[str, Any]:
        """Таймлайн одного пользователя: все поиски + фидбек события."""
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        searches_q = await self.session.execute(
            text(
                """
                SELECT id, ts, query, collection, candidates_count, branch,
                       total_ms, rerank_ms, status, top_results
                FROM search_events
                WHERE user_ip = :ip AND ts >= :since
                ORDER BY ts ASC
                """
            ),
            {"ip": user_ip, "since": since},
        )
        feedback_q = await self.session.execute(
            text(
                """
                SELECT id, ts, action, query, selected_code, position, description
                FROM feedback_events
                WHERE user_ip = :ip AND ts >= :since
                ORDER BY ts ASC
                """
            ),
            {"ip": user_ip, "since": since},
        )

        # Сливаем в один таймлайн (отсортированный по ts)
        events: list[dict[str, Any]] = []
        for s in searches_q.mappings().all():
            tr = s["top_results"] or {}
            events.append(
                {
                    "type": "search",
                    "ts": s["ts"].isoformat() if s["ts"] else None,
                    "query": s["query"],
                    "collection": s["collection"],
                    "candidates_count": s["candidates_count"],
                    "branch": s["branch"],
                    "total_ms": s["total_ms"],
                    "rerank_ms": s["rerank_ms"],
                    "status": s["status"],
                    "top_codes": [
                        item.get("code") for item in (tr.get("items") or [])[:3]
                    ],
                }
            )
        for f in feedback_q.mappings().all():
            events.append(
                {
                    "type": f["action"],  # copy|dislike
                    "ts": f["ts"].isoformat() if f["ts"] else None,
                    "query": f["query"],
                    "selected_code": f["selected_code"],
                    "position": f["position"],
                    "description": f["description"],
                }
            )
        events.sort(key=lambda e: e.get("ts") or "")

        return {
            "user_ip": user_ip,
            "window_hours": hours,
            "events": events,
            "searches_count": len([e for e in events if e["type"] == "search"]),
            "feedback_count": len([e for e in events if e["type"] in ("copy", "dislike")]),
        }


__all__ = ["SearchAnalyticsService"]
