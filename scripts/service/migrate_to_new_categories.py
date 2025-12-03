#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт миграции существующих данных в новый формат категорий.

ТОЛЬКО ДЛЯ КОЛЛЕКЦИИ ksr_main!

Старый формат path_level_N:
    path_level_1 = "Арматура"
    path_level_2 = "Арматура → Краны"
    path_level_3 = "Арматура → Краны → Кран шаровой DN50"
    path_depth = 3

Новый формат path_level_N:
    path_level_1 = "Арматура"           # Только уровень 1
    path_level_2 = "Краны"              # Только уровень 2
    path_depth = 2                      # Количество категорий (без full_description)
    full_description = "Кран шаровой DN50"   # Полное описание материала
    context_description = "Арматура → Краны → Кран шаровой DN50"  # Для эмбеддингов

Использование:
    python scripts/service/migrate_to_new_categories.py [--dry-run] [--batch-size 100]

Автор: Alexandr
Дата: 2025
"""

import os
import sys
import argparse
import logging
from typing import Optional

# Добавляем корневую директорию проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === КОНСТАНТЫ ===
COLLECTION_NAME = "ksr_main"  # Только для этой коллекции!
SEPARATOR = "→"
QDRANT_STORAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "03_processed", "qdrant_storage"
)


def parse_old_path_levels(payload: dict, separator: str = "→") -> dict:
    """
    Парсит старый формат path_level_N (накопительный) и преобразует в новый (отдельные уровни).
    
    Старый формат:
        path_level_1 = "Арматура"
        path_level_2 = "Арматура → Краны"
        path_level_3 = "Арматура → Краны → Кран шаровой"
    
    Новый формат:
        path_level_1 = "Арматура"
        path_level_2 = "Краны"
        path_depth = 2  (категории)
        full_description = "Кран шаровой"
        context_description = "Арматура → Краны → Кран шаровой"
    
    Args:
        payload: Текущий payload записи с path_level_N.
        separator: Разделитель уровней (по умолчанию "→").
    
    Returns:
        dict: Обновлённые поля для payload.
    """
    # Определяем максимальную глубину
    old_depth = payload.get("path_depth", 0)
    if old_depth == 0:
        # Ищем максимальный path_level_N
        for key in payload.keys():
            if key.startswith("path_level_"):
                try:
                    level = int(key.split("_")[-1])
                    old_depth = max(old_depth, level)
                except ValueError:
                    pass
    
    if old_depth == 0:
        # Нет path_level полей - используем description
        description = payload.get("description", "")
        if separator in description:
            parts = [p.strip() for p in description.split(separator) if p.strip()]
            if len(parts) > 1:
                new_levels = {}
                for i, part in enumerate(parts[:-1]):
                    new_levels[f"path_level_{i + 1}"] = part
                return {
                    **new_levels,
                    "path_depth": len(parts) - 1,
                    "full_description": parts[-1],
                    "context_description": description
                }
        return {
            "path_depth": 0,
            "full_description": description,
            "context_description": description
        }
    
    # Берём самый полный путь (последний уровень)
    full_path = payload.get(f"path_level_{old_depth}", "")
    
    if not full_path:
        # Fallback на description
        full_path = payload.get("description", "")
    
    # Сохраняем полный путь как context_description
    context_description = full_path
    
    # Разбиваем на части
    parts = [p.strip() for p in full_path.split(separator) if p.strip()]
    
    if not parts:
        return {
            "path_depth": 0,
            "full_description": "",
            "context_description": ""
        }
    
    # Последняя часть - full_description
    # Все предыдущие - отдельные уровни категорий
    full_description = parts[-1] if parts else ""
    category_parts = parts[:-1] if len(parts) > 1 else []
    
    new_levels = {}
    for i, part in enumerate(category_parts):
        new_levels[f"path_level_{i + 1}"] = part
    
    return {
        **new_levels,
        "path_depth": len(category_parts),
        "full_description": full_description,
        "context_description": context_description
    }


def migrate_collection(
    client: QdrantClient,
    collection_name: str,
    batch_size: int = 100,
    dry_run: bool = False
) -> dict:
    """
    Миграция записей коллекции в новый формат.
    
    Args:
        client: Клиент Qdrant.
        collection_name: Имя коллекции (только ksr_main!).
        batch_size: Размер батча для обработки.
        dry_run: Если True - только проверка, без записи.
    
    Returns:
        dict: Статистика миграции.
    """
    if collection_name != COLLECTION_NAME:
        raise ValueError(f"Миграция поддерживается только для коллекции '{COLLECTION_NAME}'!")
    
    logger.info(f"🚀 Начало миграции коллекции '{collection_name}'")
    logger.info(f"   Режим: {'DRY RUN (без записи)' if dry_run else 'ЗАПИСЬ ИЗМЕНЕНИЙ'}")
    logger.info(f"   Batch size: {batch_size}")
    
    stats = {
        "total": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": 0,
        "already_migrated": 0
    }
    
    # Scroll по всем записям
    offset = None
    
    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True  # Нужны векторы для upsert
        )
        
        if not points:
            break
        
        points_to_update = []
        
        for point in points:
            stats["total"] += 1
            payload = dict(point.payload)
            
            # Проверяем, уже мигрирована ли запись
            # Если есть full_description и context_description - уже новый формат
            if "full_description" in payload and "context_description" in payload:
                stats["already_migrated"] += 1
                continue
            
            # Проверяем, нужна ли миграция (есть path_level_2 с накопительным путём)
            path_level_2 = payload.get("path_level_2", "")
            if path_level_2 and SEPARATOR in path_level_2:
                # Старый формат - нужна миграция
                try:
                    # Парсим и преобразуем
                    new_fields = parse_old_path_levels(payload, SEPARATOR)
                    
                    # Удаляем старые path_level_N (которые могут быть лишними)
                    old_depth = payload.get("path_depth", 0)
                    for i in range(1, old_depth + 5):  # +5 для запаса
                        key = f"path_level_{i}"
                        if key in payload:
                            del payload[key]
                    
                    # Добавляем новые поля
                    payload.update(new_fields)
                    
                    if not dry_run:
                        points_to_update.append(
                            PointStruct(
                                id=point.id,
                                vector=point.vector,
                                payload=payload
                            )
                        )
                    
                    stats["migrated"] += 1
                    
                    if stats["migrated"] % 100 == 0:
                        logger.info(f"   Обработано: {stats['migrated']} записей...")
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка миграции записи {point.id}: {e}")
                    stats["errors"] += 1
            else:
                # Либо нет path_level_2, либо он уже в новом формате
                stats["skipped"] += 1
        
        # Записываем батч
        if points_to_update and not dry_run:
            client.upsert(
                collection_name=collection_name,
                points=points_to_update
            )
            logger.info(f"   ✅ Записан батч: {len(points_to_update)} записей")
        
        # Переходим к следующему батчу
        offset = next_offset
        if offset is None:
            break
    
    # Итоговая статистика
    logger.info(f"\n📊 Статистика миграции:")
    logger.info(f"   Всего записей: {stats['total']}")
    logger.info(f"   Мигрировано: {stats['migrated']}")
    logger.info(f"   Уже в новом формате: {stats['already_migrated']}")
    logger.info(f"   Пропущено (без path_level): {stats['skipped']}")
    logger.info(f"   Ошибок: {stats['errors']}")
    
    return stats


def main():
    """Главная функция скрипта миграции."""
    parser = argparse.ArgumentParser(
        description=f"Миграция коллекции {COLLECTION_NAME} в новый формат категорий"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только проверка без записи изменений"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Размер батча для обработки (по умолчанию 100)"
    )
    parser.add_argument(
        "--qdrant-path",
        type=str,
        default=QDRANT_STORAGE_PATH,
        help=f"Путь к Qdrant storage (по умолчанию: {QDRANT_STORAGE_PATH})"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("   МИГРАЦИЯ КАТЕГОРИЙ В НОВЫЙ ФОРМАТ")
    logger.info("=" * 60)
    logger.info(f"   Коллекция: {COLLECTION_NAME}")
    logger.info(f"   Qdrant path: {args.qdrant_path}")
    logger.info("")
    
    # Подключаемся к Qdrant
    if not os.path.exists(args.qdrant_path):
        logger.error(f"❌ Путь к Qdrant не найден: {args.qdrant_path}")
        sys.exit(1)
    
    try:
        client = QdrantClient(path=args.qdrant_path)
        logger.info(f"✅ Подключение к Qdrant: {args.qdrant_path}")
        
        # Проверяем существование коллекции
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            logger.error(f"❌ Коллекция '{COLLECTION_NAME}' не найдена!")
            logger.info(f"   Доступные коллекции: {collections}")
            sys.exit(1)
        
        # Запускаем миграцию
        stats = migrate_collection(
            client=client,
            collection_name=COLLECTION_NAME,
            batch_size=args.batch_size,
            dry_run=args.dry_run
        )
        
        if args.dry_run:
            logger.info("\n⚠️  DRY RUN завершён. Изменения НЕ записаны.")
            logger.info("   Для записи изменений запустите без флага --dry-run")
        else:
            logger.info("\n✅ Миграция завершена успешно!")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()

