"""search_events: persistent search analytics.

Adds a new table to record every /match call (query, per-stage timings,
user attribution, branch, candidates, top results). Three pre-built views
simplify day-to-day queries:

- v_search_stats_daily  -- daily aggregates (count, p50/p95 latency, CTR)
- v_top_queries         -- most frequent queries with avg timings
- v_zero_result_queries -- queries that returned nothing (content gaps)

JSONB is used for variable data (top_results, filter_paths) per the
Postgres JSONB best practice: typed columns for things we filter/sort on,
JSONB for variable payloads.

Revision ID: 0005_search_events
Revises: 0004_phase4_rrf_mmr
Create Date: 2026-06-16 12:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_search_events"
down_revision = "0004_phase4_rrf_mmr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # =====================================================================
    # search_events — каждое /match обращение
    # =====================================================================
    op.create_table(
        "search_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # --- атрибуция ---
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("user_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        # --- что искали ---
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("collection", sa.String(64), nullable=True),
        sa.Column("filter_paths", postgresql.JSONB(), nullable=True),
        # --- per-stage тайминги (мс) — типизированные для индексов/сортировки ---
        sa.Column("embed_ms", sa.Integer, nullable=True),
        sa.Column("qdrant_ms", sa.Integer, nullable=True),
        sa.Column("bm25_ms", sa.Integer, nullable=True),
        sa.Column("rrf_ms", sa.Integer, nullable=True),
        sa.Column("mmr_ms", sa.Integer, nullable=True),
        sa.Column("rerank_ms", sa.Integer, nullable=True),
        sa.Column("format_ms", sa.Integer, nullable=True),
        sa.Column("total_ms", sa.Integer, nullable=True),
        # --- результат ---
        sa.Column("candidates_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "branch",
            sa.String(32),
            nullable=True,
        ),  # confident|uncertain|low_confidence
        sa.Column("top_results", postgresql.JSONB(), nullable=True),
        # --- конфиг (для отладки смены моделей) ---
        sa.Column("model_embed", sa.String(128), nullable=True),
        sa.Column("model_rerank", sa.String(128), nullable=True),
        # --- статус ---
        sa.Column("status", sa.String(16), nullable=False, server_default="success"),
        sa.Column("error", sa.Text, nullable=True),
    )

    # --- индексы ---
    # BRIN на ts: дешёвый, append-only, идеален для range queries
    op.execute(
        "CREATE INDEX idx_search_events_ts_brin ON search_events USING BRIN (ts)"
    )
    # B-Tree для типичных запросов
    op.create_index("idx_search_events_ts", "search_events", [sa.text("ts DESC")])
    op.create_index(
        "idx_search_events_user_ip_ts",
        "search_events",
        ["user_ip", sa.text("ts DESC")],
    )
    op.create_index("idx_search_events_collection_ts", "search_events", ["collection", sa.text("ts DESC")])
    op.create_index("idx_search_events_branch", "search_events", ["branch"])
    op.create_index("idx_search_events_status", "search_events", ["status"])
    # Триграммный индекс для ILIKE по query (требует pg_trgm)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX idx_search_events_query_trgm ON search_events USING gin (query gin_trgm_ops)"
    )

    # =====================================================================
    # VIEW: ежедневные агрегаты
    # =====================================================================
    op.execute(
        """
        CREATE OR REPLACE VIEW v_search_stats_daily AS
        SELECT
            date_trunc('day', ts)::date AS day,
            COUNT(*)                                           AS searches,
            COUNT(DISTINCT session_id)                         AS unique_sessions,
            COUNT(DISTINCT user_ip)                            AS unique_users,
            SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END) AS zero_result,
            ROUND(
                100.0 * SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END) / COUNT(*), 2
            )                                                  AS zero_result_pct,
            ROUND(AVG(total_ms)::numeric, 0)                   AS avg_total_ms,
            ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY total_ms)) AS p50_total_ms,
            ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms)) AS p95_total_ms,
            ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY rerank_ms)) AS p95_rerank_ms,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
        FROM search_events
        WHERE status = 'success'
        GROUP BY date_trunc('day', ts)
        ORDER BY day DESC
        """
    )

    # =====================================================================
    # VIEW: топ запросов с агрегатами
    # =====================================================================
    op.execute(
        """
        CREATE OR REPLACE VIEW v_top_queries AS
        SELECT
            query,
            COUNT(*)                                     AS cnt,
            COUNT(DISTINCT session_id)                   AS unique_sessions,
            ROUND(AVG(total_ms)::numeric, 0)             AS avg_total_ms,
            ROUND(AVG(candidates_count)::numeric, 1)     AS avg_candidates,
            ROUND(AVG(rerank_ms)::numeric, 0)            AS avg_rerank_ms,
            MAX(ts)                                      AS last_seen,
            SUM(CASE WHEN candidates_count = 0 THEN 1 ELSE 0 END) AS zero_result_count
        FROM search_events
        WHERE status = 'success'
          AND ts > NOW() - INTERVAL '90 days'
        GROUP BY query
        ORDER BY cnt DESC
        """
    )

    # =====================================================================
    # VIEW: zero-result запросы (контент-гэпы)
    # =====================================================================
    op.execute(
        """
        CREATE OR REPLACE VIEW v_zero_result_queries AS
        SELECT
            query,
            COUNT(*)           AS cnt,
            COUNT(DISTINCT user_ip) AS unique_users,
            MAX(ts)            AS last_seen,
            MIN(ts)            AS first_seen
        FROM search_events
        WHERE status = 'success'
          AND candidates_count = 0
          AND ts > NOW() - INTERVAL '90 days'
        GROUP BY query
        ORDER BY cnt DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_zero_result_queries")
    op.execute("DROP VIEW IF EXISTS v_top_queries")
    op.execute("DROP VIEW IF EXISTS v_search_stats_daily")
    op.execute("DROP INDEX IF EXISTS idx_search_events_query_trgm")
    op.execute("DROP INDEX IF EXISTS idx_search_events_status")
    op.execute("DROP INDEX IF EXISTS idx_search_events_branch")
    op.execute("DROP INDEX IF EXISTS idx_search_events_collection_ts")
    op.execute("DROP INDEX IF EXISTS idx_search_events_user_ip_ts")
    op.execute("DROP INDEX IF EXISTS idx_search_events_ts")
    op.execute("DROP INDEX IF EXISTS idx_search_events_ts_brin")
    op.drop_table("search_events")
    # pg_trgm не дропаем — мог быть подключён раньше
