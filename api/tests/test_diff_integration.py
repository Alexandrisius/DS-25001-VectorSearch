"""Интеграционный тест Bug #1 + #2: импорт → повторный импорт → diff = 0.

Главный пользовательский сценарий:
  1) Пользователь импортирует Excel (255 записей, часть с «ёлочками», часть с иерархией)
  2) Загружает тот же Excel ещё раз и нажимает "Сравнить с базой"
  3) ОЖИДАЕТ 0 изменений (данные идентичны)
  4) БАГ: до фикса — 255 "изменений" с визуально одинаковыми строками

Тест воспроизводит этот сценарий на Python-порте клиентской логики diff.
"""
from __future__ import annotations

import asyncio

import pytest

from app.api.materials import get_all_codes
from app.db.postgres import get_session_maker
from app.services.cleaning_runner import CleaningRunner
from app.services.import_service import ImportService, apply_column_mapping
from app.utils.diff import analyze_changes


# loop_scope="session" — все async-тесты в этом модуле в ОДНОМ event loop.
pytestmark = [pytest.mark.asyncio(loop_scope="session"), pytest.mark.integration]


_MAPPING = {
    "code": ["Код"],
    "description": ["Название"],
    "hierarchy": ["Раздел", "Группа"],
    "code_separator": ".",
    "description_separator": " ",
}


def _build_new_records(rows: list[dict]) -> list[dict]:
    """Имитация клиентской buildRecordsFromMapping (mapping.js).

    Клиент: cleanValue → applyCleaningRules. На сервере то же самое делает
    apply_column_mapping (его зовёт Celery worker при cache_key импорте).
    Поэтому здесь мы зовём apply_column_mapping и берём те же поля.
    """
    mapped = apply_column_mapping(rows, _MAPPING)
    return [
        {
            "code": m["code"],
            "description": m["description"],
            "hierarchy": m.get("hierarchy"),
        }
        for m in mapped
    ]


async def test_diff_identical_data_shows_zero_changes(test_collection, fake_embedding):
    """Главный регрессионный сценарий.

    Импортируем 10 записей (часть с иерархией, часть с «ёлочками»).
    Затем "загружаем" те же данные заново и считаем diff.
    Ожидание: 0 modified, 0 added, 0 deleted, 10 unchanged.
    """
    raw_rows = [
        # С иерархией "→" — без фикса #1 description потеряется
        {"Код": "EX.1", "Название": "Раздел A → Группа B → Материал 1", "Раздел": "Раздел A", "Группа": "Группа B"},
        {"Код": "EX.2", "Название": "Раздел A → Группа C → Материал 2", "Раздел": "Раздел A", "Группа": "Группа C"},
        {"Код": "EX.3", "Название": "Раздел B → Группа D → Материал 3", "Раздел": "Раздел B", "Группа": "Группа D"},
        {"Код": "EX.4", "Название": "Раздел B → Группа E → Материал 4", "Раздел": "Раздел B", "Группа": "Группа E"},
        {"Код": "EX.5", "Название": "Раздел C → Группа F → Материал 5", "Раздел": "Раздел C", "Группа": "Группа F"},
        # С «ёлочками» — без фикса #2 кавычки останутся в БД
        {"Код": "EX.6", "Название": "«Агрегат электронасосный X200»", "Раздел": "", "Группа": ""},
        {"Код": "EX.7", "Название": '"Кран шаровой DN50"', "Раздел": "", "Группа": ""},
        # Простые
        {"Код": "EX.8", "Название": "Задвижка клиновая", "Раздел": "", "Группа": ""},
        {"Код": "EX.9", "Название": "Котёл газовый", "Раздел": "", "Группа": ""},
        {"Код": "EX.10", "Название": "Щит шкафной напольный", "Раздел": "", "Группа": ""},
    ]

    # Шаг 1: первый импорт (column mapping, как делает Celery worker)
    records = _build_new_records(raw_rows)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        cleaning = CleaningRunner(session)
        await cleaning.load_rules()
        svc = ImportService(session, embedding_service=fake_embedding, cleaning=cleaning)
        result1 = await svc.import_records(test_collection, records)
        await session.commit()

    assert result1["materials"] == 10, f"ожидалось 10 материалов, получено {result1['materials']}"

    await asyncio.sleep(0.5)  # Qdrant eventual consistency

    # Шаг 2: existing records (то, что в Qdrant) — после фикса #1 корректное поле
    async with SessionLocal() as session:
        existing_resp = await get_all_codes(database=test_collection.name, session=session)
        existing = existing_resp["records"]

    # Шаг 3: new records (то, что клиент построит из того же Excel)
    new_records = _build_new_records(raw_rows)

    # Шаг 4: diff
    diff = analyze_changes(new_records, existing)

    # Шаг 5: ОЖИДАНИЕ — ноль изменений
    assert diff["added"] == [], f"ожидалось 0 added, получили {len(diff['added'])}: {[r['code'] for r in diff['added']]}"
    assert diff["modified"] == [], (
        f"ожидалось 0 modified, получили {len(diff['modified'])}: "
        f"{[r['code'] for r in diff['modified']]}\n"
        f"Пример различия: {diff['modified'][0] if diff['modified'] else '—'}"
    )
    assert diff["deleted"] == [], f"ожидалось 0 deleted, получили {len(diff['deleted'])}"
    assert diff["unchanged"] == 10, f"ожидалось 10 unchanged, получили {diff['unchanged']}"


async def test_diff_only_one_changed_record(test_collection, fake_embedding):
    """Sanity check: diff всё-таки находит реальные изменения."""
    raw_rows = [
        {"Код": "EX.A", "Название": "Material A", "Раздел": "", "Группа": ""},
        {"Код": "EX.B", "Название": "Material B original", "Раздел": "", "Группа": ""},
    ]
    records = _build_new_records(raw_rows)

    SessionLocal = get_session_maker()
    async with SessionLocal() as session:
        cleaning = CleaningRunner(session)
        await cleaning.load_rules()
        svc = ImportService(session, embedding_service=fake_embedding, cleaning=cleaning)
        await svc.import_records(test_collection, records)
        await session.commit()

    await asyncio.sleep(0.5)

    new_rows = [
        {"Код": "EX.A", "Название": "Material A", "Раздел": "", "Группа": ""},
        {"Код": "EX.B", "Название": "Material B CHANGED", "Раздел": "", "Группа": ""},
        {"Код": "EX.C", "Название": "Material C", "Раздел": "", "Группа": ""},
    ]

    async with SessionLocal() as session:
        existing = (await get_all_codes(database=test_collection.name, session=session))["records"]

    new_records = _build_new_records(new_rows)
    diff = analyze_changes(new_records, existing)

    assert len(diff["added"]) == 1
    assert diff["added"][0]["code"] == "EX.C"
    assert len(diff["modified"]) == 1
    assert diff["modified"][0]["code"] == "EX.B"
    assert diff["modified"][0]["oldDescription"] == "Material B original"
    assert diff["modified"][0]["newDescription"] == "Material B CHANGED"
    assert len(diff["deleted"]) == 0
    assert diff["unchanged"] == 1
