"""Shared pytest fixtures for api/tests/.

Использует живые Postgres и Qdrant (как у dev-окружения в docker-compose).
Без них — тесты скипаются с понятной ошибкой, не падают в CI.

Запуск:
    docker compose exec api pytest tests/ -v
    docker compose exec api pytest tests/ -v -m "not integration"   # только юниты

ВАЖНО про event loop:
    asyncpg pool привязан к event loop. Глобальный engine через lru_cache
    создаётся в первом loop, в котором его позвали. Если тесты бегут в
    разных loop'ах — connections перепутываются, всё падает.

    Решение: session-scoped loop + пересоздаём engine до КАЖДОГО теста
    с NullPool (без пула — каждое соединение свежее).
"""
from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

try:
    from app.config import get_settings
    from app.db.qdrant import get_qdrant_client
    from app.models.collection import Collection as CollectionModel

    _HAS_INFRA = True
except Exception:  # pragma: no cover
    _HAS_INFRA = False


# --------------------------------------------------------------- event loop
@pytest.fixture(scope="session")
def event_loop():
    """Один event loop на всю сессию — обязательно для asyncpg pool."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ----------------------------------------------------------------- infra skip
def _infra_unavailable() -> bool:
    if not _HAS_INFRA:
        return True
    if not os.getenv("DATABASE_URL"):
        return True
    return False


def pytest_collection_modifyitems(config, items):
    if not _infra_unavailable():
        return
    skip = pytest.mark.skip(reason="infra (Postgres/Qdrant) недоступна")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ----------------------------------------------------------------- fixtures
def _make_test_session_maker():
    """Создать engine с NullPool (без пула) и async_sessionmaker.

    NullPool гарантирует, что каждое соединение создаётся и закрывается
    заново — никаких висящих connections через loop-переключения.
    """
    from sqlalchemy.pool import NullPool

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async session к Postgres с NullPool — безопасно для тестов с любым loop."""
    if _infra_unavailable():
        pytest.skip("infra недоступна")
    SessionLocal = _make_test_session_maker()
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest_asyncio.fixture
async def test_collection(db_session: AsyncSession):
    """Создаёт временную коллекцию test_diff_<uuid> и удаляет после теста."""
    from sqlalchemy import delete as sa_delete

    if _infra_unavailable():
        pytest.skip("infra недоступна")

    name = f"test_diff_{uuid.uuid4().hex[:8]}"
    coll = CollectionModel(
        name=name,
        description="temporary collection for diff tests",
        dimension=2560,
        visible=True,
        locked=False,
    )
    db_session.add(coll)
    await db_session.commit()

    from qdrant_client.http import models as qm

    qdrant = get_qdrant_client()
    qdrant.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=2560, distance=qm.Distance.COSINE),
    )

    try:
        yield coll
    finally:
        try:
            qdrant.delete_collection(name)
        except Exception:
            pass
        try:
            await db_session.execute(
                sa_delete(CollectionModel).where(CollectionModel.name == name)
            )
            await db_session.commit()
        except Exception:
            try:
                await db_session.rollback()
            except Exception:
                pass


@pytest.fixture
def fake_embedding() -> Any:
    """Мок EmbeddingService: возвращает список 2560d нулей нужной длины."""
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    mock.batch_size = 200

    async def _embed_batch(texts, *args, **kwargs):
        return [[0.0] * 2560 for _ in texts]

    mock.embed_batch = _embed_batch
    return mock
