"""initial schema: collections, materials, folders, statuses, cleaning_rules,
api_providers, background_jobs, feedback_events + seed default statuses

Revision ID: 0001
Revises:
Create Date: 2026-06-11 00:01:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # ENUMS / типы
    # =====================================================================
    job_status = postgresql.ENUM(
        "pending", "processing", "completed", "error", "cancelled",
        name="job_status",
        create_type=True,
    )

    # =====================================================================
    # collections — коллекции Qdrant
    # =====================================================================
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "columns_mapping",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{\"code\": \"code\", \"description\": \"description\"}'::jsonb"),
        ),
        sa.Column("cosine_threshold", sa.Float, nullable=False, server_default="0.45"),
        sa.Column("rerank_threshold", sa.Float, nullable=False, server_default="0.6"),
        sa.Column("visible", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("dimension", sa.Integer, nullable=False),
        sa.Column("last_updated", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_collections_visible", "collections", ["visible"])

    # =====================================================================
    # statuses — статусы записей
    # =====================================================================
    op.create_table(
        "statuses",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )

    # =====================================================================
    # cleaning_rules — regex-правила очистки
    # =====================================================================
    op.create_table(
        "cleaning_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("replacement", sa.Text, nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "apply_to_columns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"*\"]'::jsonb"),
        ),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # =====================================================================
    # api_providers — конфигурация OpenRouter (и будущих)
    # =====================================================================
    op.create_table(
        "api_providers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(32), unique=True, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("api_key_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("model_embed", sa.String(128), nullable=False, server_default="qwen/qwen3-embedding-4b"),
        sa.Column("model_rerank", sa.String(128), nullable=False, server_default="qwen/qwen3-rerank-8b"),
        sa.Column("batch_size", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_workers", sa.Integer, nullable=False, server_default="3"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # =====================================================================
    # materials — зеркало Qdrant для SQL-фильтрации
    # =====================================================================
    op.create_table(
        "materials",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("collection_id", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("full_description", sa.Text, nullable=True),
        sa.Column("context_description", sa.Text, nullable=True),
        sa.Column("path_levels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("path_depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("qdrant_point_id", postgresql.UUID(astext_type=sa.Text()), nullable=False),
        sa.Column("status_id", sa.String(32), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["status_id"], ["statuses.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("collection_id", "code", name="uq_materials_collection_code"),
    )
    op.create_index("idx_materials_collection_code", "materials", ["collection_id", "code"])
    op.create_index("idx_materials_status", "materials", ["status_id"])
    op.create_index("idx_materials_updated", "materials", ["updated_at"])

    # =====================================================================
    # folders — иерархия категорий
    # =====================================================================
    op.create_table(
        "folders",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("collection_id", sa.Integer, nullable=False),
        sa.Column("full_path", sa.Text, nullable=False),
        sa.Column("leaf_name", sa.String(256), nullable=False),
        sa.Column("parent_id", sa.BigInteger, nullable=True),
        sa.Column("level", sa.Integer, nullable=False),
        sa.Column("items_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("qdrant_point_id", postgresql.UUID(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["folders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("collection_id", "full_path", name="uq_folders_collection_path"),
    )
    op.create_index("idx_folders_collection", "folders", ["collection_id"])
    op.create_index("idx_folders_parent", "folders", ["parent_id"])
    op.create_index("idx_folders_level", "folders", ["level"])

    # =====================================================================
    # material_folders — M2M
    # =====================================================================
    op.create_table(
        "material_folders",
        sa.Column("material_id", sa.BigInteger, nullable=False),
        sa.Column("folder_id", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["folder_id"], ["folders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("material_id", "folder_id", name="pk_material_folders"),
    )
    op.create_index("idx_material_folders_folder", "material_folders", ["folder_id"])

    # =====================================================================
    # background_jobs — фоновые задачи
    # =====================================================================
    job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(astext_type=sa.Text()), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="job_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("details", sa.Text, nullable=False, server_default=""),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_jobs_status_created", "background_jobs", ["status", "created_at"])
    op.create_index("idx_jobs_type", "background_jobs", ["type"])

    # =====================================================================
    # feedback_events — аналитика
    # =====================================================================
    op.create_table(
        "feedback_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("selected_code", sa.String(64), nullable=True),
        sa.Column("position", sa.Integer, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("collection", sa.String(64), nullable=True),
        sa.Column("reranker_score", sa.Float, nullable=True),
        sa.Column("cosine_similarity", sa.Float, nullable=True),
        sa.Column("user_ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
    )
    op.create_index("idx_feedback_collection_ts", "feedback_events", ["collection", "ts"])
    op.create_index("idx_feedback_action", "feedback_events", ["action"])
    op.create_index("idx_feedback_query_trgm", "feedback_events", ["query"], postgresql_using="gin")

    # =====================================================================
    # Сидинг: дефолтные статусы
    # =====================================================================
    op.execute(
        """
        INSERT INTO statuses (id, label, color, is_default, sort_order) VALUES
            ('active',     'Активная',     '#10b981', TRUE,  10),
            ('draft',      'Черновик',     '#f59e0b', FALSE, 20),
            ('deprecated', 'Устаревшая',   '#ef4444', FALSE, 30)
        """
    )

    # Сидинг: дефолтное правило очистки
    op.execute(
        """
        INSERT INTO cleaning_rules (name, pattern, replacement, enabled, apply_to_columns, sort_order) VALUES
            ('Удалить «Раздел/Группа N.N»', '^(Раздел|Группа)\\s+[\\d\\.\\s]+', '', TRUE, '["*"]'::jsonb, 10)
        """
    )

    # Сидинг: дефолтный провайдер (выключен, ключ пуст)
    op.execute(
        """
        INSERT INTO api_providers (name, enabled, model_embed, model_rerank, batch_size, max_workers) VALUES
            ('openrouter', FALSE, 'qwen/qwen3-embedding-4b', 'qwen/qwen3-rerank-8b', 10, 3)
        """
    )


def downgrade() -> None:
    op.drop_table("feedback_events")
    op.drop_table("background_jobs")
    op.drop_table("material_folders")
    op.drop_table("folders")
    op.drop_table("materials")
    op.drop_table("api_providers")
    op.drop_table("cleaning_rules")
    op.drop_table("statuses")
    op.drop_table("collections")
    op.execute("DROP TYPE IF EXISTS job_status")
