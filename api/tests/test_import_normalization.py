"""Интеграционный тест Bug #2: сервер должен снимать симметричные кавычки.

ДО фикса (в api/app/services/import_service.py:99, 207):
    parts() делает только str(...).strip()
    → «ёлочки» в Excel сохраняются в Qdrant как есть
    → клиентский diff их снимает → ложные "изменения"

ПОСЛЕ фикса:
    parts() делает str(...).strip() → strip_symmetric_quotes
    → клиент и сервер дают идентичный результат

Тест:
  1) apply_column_mapping с кавычками → результат без кавычек
  2) import_records end-to-end с кавычками → Qdrant payload без кавычек
"""
from __future__ import annotations

import asyncio
import uuid as uuid_mod

import pytest

from app.db.postgres import get_session_maker
from app.services.cleaning_runner import CleaningRunner
from app.services.import_service import (
    ImportService,
    apply_column_mapping,
)
from app.utils.path_levels import generate_path_levels
from app.utils.text import strip_symmetric_quotes


# loop_scope="session" — все async-тесты в этом модуле в ОДНОМ event loop.
# pytest.mark.asyncio(loop_scope="session") срабатывает на async-тесты;
# sync-тесты (юниты apply_column_mapping) автоматически игнорируют марк.
pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.integration]


# --------------------------------------------------------------------- юнит
def test_apply_column_mapping_strips_symmetric_quotes():
    """Юнит: маппинг колонок снимает «ёлочки» с краёв каждой ячейки."""
    rows = [
        {"Код": "EX.1", "Название": "«Агрегат электронасосный»"},
        {"Код": "EX.2", "Название": '"Кран шаровой"'},
    ]
    mapping = {
        "code": ["Код"],
        "description": ["Название"],
        "code_separator": ".",
        "description_separator": " ",
    }
    mapped = apply_column_mapping(rows, mapping)

    assert len(mapped) == 2
    assert mapped[0]["code"] == "EX.1"
    # Главный ассерт: кавычки сняты
    assert mapped[0]["description"] == "Агрегат электронасосный"
    assert mapped[1]["description"] == "Кран шаровой"


def test_apply_column_mapping_no_quotes_unchanged():
    """Регрессия: без кавычек поведение не меняется."""
    rows = [
        {"Код": "EX.1", "Название": "Агрегат электронасосный"},
    ]
    mapping = {"code": ["Код"], "description": ["Название"]}
    mapped = apply_column_mapping(rows, mapping)
    assert mapped[0]["description"] == "Агрегат электронасосный"


def test_apply_column_mapping_only_one_side_quote_kept():
    """Граничный случай: кавычка только с одного края — НЕ трогаем.

    Симметрично JS-семантике: «text без закрывающей» — не пара.
    """
    rows = [
        {"Код": "EX.1", "Название": "«Агрегат"},  # только открывающая
    ]
    mapping = {"code": ["Код"], "description": ["Название"]}
    mapped = apply_column_mapping(rows, mapping)
    # Остаётся как есть — strip_symmetric_quotes не нашёл пару
    assert mapped[0]["description"] == "«Агрегат"


# ----------------------------------------------------- интеграционный (БД)
async def test_import_records_strips_quotes_before_saving_to_qdrant(
    test_collection, fake_embedding
):
    """E2E: ImportService.import_records сохраняет в Qdrant описание БЕЗ кавычек.

    До фикса: в Qdrant будет «Агрегат». После фикса: «Агрегат» → Агрегат.
    """
    records = [
        {
            "code": "EX.QUOTE.001",
            "description": "«Агрегат электронасосный X200»",
        },
        {
            "code": "EX.QUOTE.002",
            "description": '"Кран шаровой DN50"',
        },
    ]

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        cleaning = CleaningRunner(session)
        await cleaning.load_rules()  # принудительно инициализируем кэш
        svc = ImportService(session, embedding_service=fake_embedding, cleaning=cleaning)
        result = await svc.import_records(test_collection, records)
        await session.commit()

    assert result["materials"] == 2

    # Проверяем Qdrant напрямую
    from app.db.qdrant import get_qdrant_client

    qdrant = get_qdrant_client()
    # eventuelly consistent — пауза
    await asyncio.sleep(0.5)

    # EX.QUOTE.001
    p1 = qdrant.retrieve(
        collection_name=test_collection.name,
        ids=[uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "EX.QUOTE.001")],
        with_payload=True,
        with_vectors=False,
    )
    assert len(p1) == 1
    desc1 = p1[0].payload.get("description", "")
    assert desc1 == "Агрегат электронасосный X200", (
        f"Кавычки должны быть сняты, получили: {desc1!r}"
    )

    # EX.QUOTE.002
    p2 = qdrant.retrieve(
        collection_name=test_collection.name,
        ids=[uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "EX.QUOTE.002")],
        with_payload=True,
        with_vectors=False,
    )
    assert len(p2) == 1
    desc2 = p2[0].payload.get("description", "")
    assert desc2 == "Кран шаровой DN50"


async def test_import_records_path_levels_strip_quotes_too(
    test_collection, fake_embedding
):
    """path_level_N значения тоже проходят strip_symmetric_quotes (вдруг там есть)."""
    records = [
        {
            "code": "EX.PATH.001",
            "description": "Material X",
            "hierarchy": "«Раздел A» → «Группа B»",
        },
    ]

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        cleaning = CleaningRunner(session)
        await cleaning.load_rules()
        svc = ImportService(session, embedding_service=fake_embedding, cleaning=cleaning)
        await svc.import_records(test_collection, records)
        await session.commit()

    from app.db.qdrant import get_qdrant_client

    qdrant = get_qdrant_client()
    await asyncio.sleep(0.5)
    p = qdrant.retrieve(
        collection_name=test_collection.name,
        ids=[uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, "EX.PATH.001")],
        with_payload=True,
        with_vectors=False,
    )
    assert len(p) == 1
    pl = p[0].payload
    assert pl["path_level_1"] == "Раздел A", f"got: {pl.get('path_level_1')!r}"
    assert pl["path_level_2"] == "Группа B", f"got: {pl.get('path_level_2')!r}"


# Прямая проверка: get_all_codes после импорта с кавычками не возвращает их
async def test_get_all_codes_after_quote_import_returns_clean_description(
    test_collection, fake_embedding
):
    """Симметрия клиент↔сервер: после импорта с «ёлочками» /get_all_codes
    возвращает описание без кавычек. Клиент (diff) тоже снимет → 0 modified.
    """
    from app.api.materials import get_all_codes

    records = [{"code": "EX.SYM.001", "description": "«Material»"}]

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        cleaning = CleaningRunner(session)
        await cleaning.load_rules()
        svc = ImportService(session, embedding_service=fake_embedding, cleaning=cleaning)
        await svc.import_records(test_collection, records)
        await session.commit()

    await asyncio.sleep(0.5)

    async with SessionLocal() as session:
        result = await get_all_codes(database=test_collection.name, session=session)

    rec = result["records"]["EX.SYM.001"]
    # Без «ёлочек»
    assert rec["description"] == "Material", f"got: {rec['description']!r}"
    assert "«" not in rec["description"]
    assert "»" not in rec["description"]
