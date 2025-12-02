#!/usr/bin/env python3
"""
Скрипт миграции: Добавление полей path_level_N в существующие записи Qdrant.

Этот скрипт добавляет поля иерархии (path_level_1, path_level_2, ..., path_depth)
в payload существующих записей для поддержки фильтрации по категориям.

Использование:
    python scripts/services/migrate_path_levels.py [--collection COLLECTION_NAME] [--dry-run]

Параметры:
    --collection : Имя конкретной коллекции для миграции (по умолчанию - все коллекции)
    --dry-run    : Режим "сухого прогона" - показывает что будет сделано без изменений
    --separator  : Разделитель иерархии в description (по умолчанию "→")

Примеры:
    # Миграция всех коллекций
    python scripts/pipelines/04_migrate_path_levels.py
    
    # Миграция конкретной коллекции
    python scripts/service/migrate_path_levels.py --collection ksr_main
    
    # Сухой прогон для проверки
    python scripts/pipelines/04_migrate_path_levels.py --dry-run

Автор: Alexandr
Дата: 2025-12-02
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

# Добавляем корень проекта в путь для импорта config
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config import QDRANT_STORAGE_PATH, VECTOR_DATABASES_CONFIG
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def generate_path_levels(description: str, separator: str = "→") -> dict:
    """
    Генерирует поля path_level_N из иерархического описания.
    
    Разбивает description по разделителю и создает набор полей для
    эффективной фильтрации в Qdrant по уровням вложенности.
    
    Пример:
        Input:  "Арматура → Краны → Кран 15"
        Output: {
            "path_level_1": "Арматура",
            "path_level_2": "Арматура → Краны",
            "path_level_3": "Арматура → Краны → Кран 15",
            "path_depth": 3
        }
    
    Args:
        description (str): Полное описание с иерархией, разделенной separator.
        separator (str): Разделитель уровней иерархии (по умолчанию "→").
    
    Returns:
        dict: Словарь с полями path_level_1..N и path_depth.
    """
    # Если нет разделителя в строке - возвращаем один уровень
    if separator not in description:
        return {
            "path_level_1": description.strip(),
            "path_depth": 1
        }
    
    # Разбиваем по разделителю и очищаем от лишних пробелов
    parts = [part.strip() for part in description.split(separator)]
    # Фильтруем пустые части (на случай двойных разделителей)
    parts = [p for p in parts if p]
    
    if not parts:
        return {"path_depth": 0}
    
    result = {"path_depth": len(parts)}
    
    # Генерируем path_level_1, path_level_2, ... path_level_N
    # Каждый уровень содержит полный путь до этого уровня
    for i in range(len(parts)):
        # Собираем путь до текущего уровня включительно
        level_path = f" {separator} ".join(parts[:i + 1])
        result[f"path_level_{i + 1}"] = level_path
    
    return result


def load_collections_config() -> Dict:
    """
    Загрузка конфигурации коллекций из vector_databases.json.
    
    Returns:
        Dict: Конфигурация коллекций или пустой словарь.
    """
    if not VECTOR_DATABASES_CONFIG.exists():
        logger.warning(f"⚠️ Файл конфигурации не найден: {VECTOR_DATABASES_CONFIG}")
        return {}
    
    with open(VECTOR_DATABASES_CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)


def needs_migration(payload: dict) -> bool:
    """
    Проверяет, нужна ли миграция для данной записи.
    
    Args:
        payload: Текущий payload записи.
    
    Returns:
        bool: True если запись не содержит path_level_1.
    """
    return "path_level_1" not in payload


def migrate_collection(
    client: QdrantClient,
    collection_name: str,
    separator: str = "→",
    dry_run: bool = False,
    batch_size: int = 100
) -> dict:
    """
    Миграция одной коллекции - добавление path_level_N полей.
    
    Args:
        client: Клиент Qdrant.
        collection_name: Имя коллекции.
        separator: Разделитель иерархии.
        dry_run: Если True - только анализ без изменений.
        batch_size: Размер батча для обновления.
    
    Returns:
        dict: Статистика миграции.
    """
    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "sample_before": None,
        "sample_after": None
    }
    
    logger.info(f"📂 Начинаем миграцию коллекции: {collection_name}")
    
    # Получаем информацию о коллекции
    try:
        collection_info = client.get_collection(collection_name)
        total_points = collection_info.points_count
        logger.info(f"   📊 Всего записей: {total_points:,}")
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации о коллекции: {e}")
        return stats
    
    # Итерируемся по всем записям через scroll API
    offset = None
    batch_num = 0
    points_to_update = []
    
    while True:
        # Получаем батч записей
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False  # Векторы не нужны для обновления payload
        )
        
        if not records:
            break
        
        batch_num += 1
        
        for point in records:
            stats["total"] += 1
            
            # Проверяем, нужна ли миграция
            if not needs_migration(point.payload):
                stats["skipped"] += 1
                continue
            
            # Получаем description для генерации path_levels
            description = point.payload.get("description", "")
            
            if not description:
                logger.warning(f"   ⚠️ Пустое description у записи {point.id}")
                stats["errors"] += 1
                continue
            
            # Генерируем новые поля
            path_levels = generate_path_levels(description, separator)
            
            # Сохраняем пример для отчета
            if stats["sample_before"] is None:
                stats["sample_before"] = {
                    "id": str(point.id),
                    "description": description[:100] + "..." if len(description) > 100 else description,
                    "payload_keys": list(point.payload.keys())
                }
                stats["sample_after"] = {
                    "id": str(point.id),
                    "description": description[:100] + "..." if len(description) > 100 else description,
                    "new_fields": path_levels
                }
            
            # Добавляем в очередь на обновление
            points_to_update.append({
                "id": point.id,
                "path_levels": path_levels
            })
            stats["migrated"] += 1
        
        # Применяем обновления батчами
        if len(points_to_update) >= batch_size and not dry_run:
            _apply_updates(client, collection_name, points_to_update)
            points_to_update = []
        
        # Прогресс
        progress = (stats["total"] / total_points) * 100 if total_points > 0 else 0
        logger.info(
            f"   📈 Прогресс: {progress:.1f}% | "
            f"Обработано: {stats['total']:,} | "
            f"К миграции: {stats['migrated']:,} | "
            f"Пропущено: {stats['skipped']:,}"
        )
        
        # Переход к следующему батчу
        offset = next_offset
        if offset is None:
            break
    
    # Применяем оставшиеся обновления
    if points_to_update and not dry_run:
        _apply_updates(client, collection_name, points_to_update)
    
    return stats


def _apply_updates(client: QdrantClient, collection_name: str, updates: List[dict]):
    """
    Применяет обновления payload для списка точек.
    
    Args:
        client: Клиент Qdrant.
        collection_name: Имя коллекции.
        updates: Список обновлений [{id, path_levels}, ...].
    """
    try:
        for update in updates:
            # Используем set_payload для обновления без перезаписи существующих полей
            client.set_payload(
                collection_name=collection_name,
                payload=update["path_levels"],
                points=[update["id"]]
            )
    except Exception as e:
        logger.error(f"❌ Ошибка обновления payload: {e}")


def main():
    """Главная функция скрипта миграции."""
    
    # === ПАРСИНГ АРГУМЕНТОВ ===
    parser = argparse.ArgumentParser(
        description="Миграция: добавление path_level_N в записи Qdrant"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Имя конкретной коллекции (по умолчанию - все)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Режим сухого прогона (без изменений)"
    )
    parser.add_argument(
        "--separator",
        type=str,
        default="→",
        help="Разделитель иерархии (по умолчанию →)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Размер батча для обработки (по умолчанию 100)"
    )
    
    args = parser.parse_args()
    
    # === ВЫВОД ЗАГОЛОВКА ===
    logger.info("=" * 70)
    logger.info("🔄 МИГРАЦИЯ: Добавление полей path_level_N в Qdrant")
    logger.info("=" * 70)
    
    if args.dry_run:
        logger.info("⚠️  РЕЖИМ СУХОГО ПРОГОНА - изменения НЕ будут применены!")
    
    logger.info(f"📂 Путь к Qdrant: {QDRANT_STORAGE_PATH}")
    logger.info(f"🔤 Разделитель:   '{args.separator}'")
    logger.info(f"📦 Размер батча:  {args.batch_size}")
    logger.info("=" * 70)
    
    # === ПОДКЛЮЧЕНИЕ К QDRANT ===
    logger.info("🔌 Подключение к Qdrant...")
    client = QdrantClient(path=str(QDRANT_STORAGE_PATH))
    
    # === ОПРЕДЕЛЕНИЕ КОЛЛЕКЦИЙ ДЛЯ МИГРАЦИИ ===
    collections = [c.name for c in client.get_collections().collections]
    
    if not collections:
        logger.warning("⚠️ Коллекции не найдены в Qdrant!")
        return
    
    logger.info(f"📚 Найдено коллекций: {len(collections)}")
    
    if args.collection:
        if args.collection not in collections:
            logger.error(f"❌ Коллекция '{args.collection}' не найдена!")
            logger.info(f"   Доступные: {', '.join(collections)}")
            return
        collections = [args.collection]
    
    # === МИГРАЦИЯ ===
    start_time = time.time()
    total_stats = {
        "collections": 0,
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0
    }
    
    for collection_name in collections:
        logger.info("")
        stats = migrate_collection(
            client=client,
            collection_name=collection_name,
            separator=args.separator,
            dry_run=args.dry_run,
            batch_size=args.batch_size
        )
        
        total_stats["collections"] += 1
        total_stats["total"] += stats["total"]
        total_stats["migrated"] += stats["migrated"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]
        
        # Вывод примера (для первой коллекции)
        if stats["sample_before"] and total_stats["collections"] == 1:
            logger.info("")
            logger.info("📋 Пример преобразования:")
            logger.info(f"   До:    {stats['sample_before']['payload_keys']}")
            logger.info(f"   После: + {list(stats['sample_after']['new_fields'].keys())}")
    
    # === ИТОГИ ===
    elapsed = time.time() - start_time
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("📊 ИТОГИ МИГРАЦИИ")
    logger.info("=" * 70)
    logger.info(f"   ✅ Коллекций обработано: {total_stats['collections']}")
    logger.info(f"   📄 Всего записей:        {total_stats['total']:,}")
    logger.info(f"   🔄 Мигрировано:          {total_stats['migrated']:,}")
    logger.info(f"   ⏭️ Пропущено (уже OK):   {total_stats['skipped']:,}")
    logger.info(f"   ❌ Ошибок:               {total_stats['errors']}")
    logger.info(f"   ⏱️ Время выполнения:     {elapsed:.1f}с")
    logger.info("=" * 70)
    
    if args.dry_run:
        logger.info("⚠️  Это был сухой прогон. Запустите без --dry-run для применения изменений.")


if __name__ == "__main__":
    main()

