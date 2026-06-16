"""Интеграционный тест Bug #1: get_all_codes возвращает правильное description.

ДО фикса (в api/app/api/materials.py:145-149):
    full = payload.get("full_description") or payload.get("description", "")
    d = {"description": full, "full_description": full, ...}
    → description = лист (последний сегмент после →)
    → клиент сравнивает полный текст с листом → 255 ложных modified

ПОСЛЕ фикса:
    desc = payload.get("description", "")
    full = payload.get("full_description") or desc
    d = {"description": desc, "full_description": full, ...}
    → description = полный текст, full_description = лист

Тест помечен @pytest.mark.integration и скипается без Postgres+Qdrant.
"""
from __future__ import annotations

import uuid as uuid_mod

import pytest
from qdrant_client.http import models as qm

from app.api.materials import get_all_codes
from app.db.qdrant import get_qdrant_client
from app.db.postgres import get_session_maker
from app.services.collection_service import CollectionService


# loop_scope="session" — все async-тесты в этом модуле в ОДНОМ event loop.
# Иначе asyncpg pool путает connections между loop'ами.
pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.integration]


def _make_point(code: str, desc: str, full_desc: str, path_depth: int = 2) -> qm.PointStruct:
    """Собрать точку как это делает ImportService._upsert_to_qdrant_chunk."""
    payload: dict = {
        "code": code,
        "description": desc,
        "full_description": full_desc,
        "context_description": desc,
        "path_depth": path_depth,
        "is_folder": False,
    }
    # path_level_1, path_level_2, ...
    if path_depth:
        parts = desc.split("→")
        for i in range(path_depth):
            if i < len(parts):
                payload[f"path_level_{i + 1}"] = parts[i].strip()
    return qm.PointStruct(
        id=uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, code),
        vector=[0.0] * 2560,
        payload=payload,
    )


async def test_get_all_codes_returns_full_description_not_leaf(test_collection):
    """Главный регрессионный тест Bug #1.

    Сценарий: в Qdrant лежит запись с иерархией "Раздел A → Группа B → Материал C".
    Qdrant хранит:
      - description       = "Раздел A → Группа B → Материал C" (полный)
      - full_description  = "Материал C"                       (лист)

    /get_all_codes должен вернуть description = полный, full_description = лист.
    До фикса — оба поля = лист. После фикса — корректно.
    """
    full_text = "Раздел A → Группа B → Материал C"
    leaf = "Материал C"

    qdrant = get_qdrant_client()
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[_make_point("EX.A.001", full_text, leaf, path_depth=2)],
    )
    # Небольшая пауза для eventual consistency Qdrant
    import asyncio
    await asyncio.sleep(0.3)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    assert "EX.A.001" in result["records"]
    rec = result["records"]["EX.A.001"]
    # Главные ассерты — то, что ломалось до фикса
    assert rec["description"] == full_text, (
        f"description должен быть полный текст, не лист. "
        f"Получили: {rec['description']!r}"
    )
    assert rec["full_description"] == leaf, (
        f"full_description должен быть лист. Получили: {rec['full_description']!r}"
    )


async def test_get_all_codes_no_hierarchy_unchanged(test_collection):
    """Когда иерархии нет — description == full_description (бэк-совместимость)."""
    text = "Простое описание без иерархии"
    qdrant = get_qdrant_client()
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[_make_point("EX.B.001", text, text, path_depth=0)],
    )
    import asyncio
    await asyncio.sleep(0.3)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    rec = result["records"]["EX.B.001"]
    assert rec["description"] == text
    assert rec["full_description"] == text


async def test_get_all_codes_preserves_path_levels(test_collection):
    """path_level_N поля должны быть скопированы (используются в folder-diff)."""
    full_text = "Раздел A → Группа B → Материал C"
    qdrant = get_qdrant_client()
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[_make_point("EX.C.001", full_text, "Материал C", path_depth=2)],
    )
    import asyncio
    await asyncio.sleep(0.3)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    rec = result["records"]["EX.C.001"]
    assert rec["path_level_1"] == "Раздел A"
    assert rec["path_level_2"] == "Группа B"
    assert rec["path_depth"] == 2


async def test_get_all_codes_skips_folders(test_collection):
    """Папки (is_folder=True) не должны попасть в /get_all_codes."""
    qdrant = get_qdrant_client()
    # Материал
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[_make_point("EX.M.001", "Material", "Material", path_depth=0)],
    )
    # Папка
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[qm.PointStruct(
            id=uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "FOLDER::Group A"),
            vector=[0.0] * 2560,
            payload={
                "code": "FOLDER::Group A",
                "description": "Group A",
                "full_path": "Group A",
                "leaf_name": "Group A",
                "path_depth": 1,
                "is_folder": True,
            },
        )],
    )
    import asyncio
    await asyncio.sleep(0.3)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    assert "EX.M.001" in result["records"]
    assert "FOLDER::Group A" not in result["records"]


async def test_get_all_codes_skips_records_without_code(test_collection):
    """Точки без поля code (а такие не должны быть) — игнорируются, не ломают ответ."""
    qdrant = get_qdrant_client()
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[qm.PointStruct(
            id=uuid_mod.uuid4(),
            vector=[0.0] * 2560,
            payload={"description": "no code here", "full_description": "no code", "is_folder": False},
        )],
    )
    qdrant.upsert(
        collection_name=test_collection.name,
        points=[_make_point("EX.D.001", "OK", "OK", path_depth=0)],
    )
    import asyncio
    await asyncio.sleep(0.3)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    assert "EX.D.001" in result["records"]
    assert result["total"] == 1
