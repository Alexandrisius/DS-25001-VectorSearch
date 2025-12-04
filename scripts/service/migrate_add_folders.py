# migrate_add_folders.py
"""
Скрипт миграции для добавления индексированных папок в существующие коллекции Qdrant.

Этот скрипт решает проблему поиска папок по короткому запросу.
Он извлекает уникальные папки (категории) из материалов и индексирует их
с флагом is_folder=true и полем leaf_name для точного rerank.

Архитектура "Contextual Path with Leaf Focus":
- full_path: полный путь папки (для генерации эмбеддинга с контекстом)
- leaf_name: название конечной папки (для rerank по короткому запросу)

ВАЖНО: Скрипт работает НАПРЯМУЮ с Qdrant без необходимости запуска сервера.
Это позволяет использовать все ресурсы GPU для максимальной производительности.

Использование:
    # Миграция конкретной коллекции
    python scripts/service/migrate_add_folders.py --collection ksr_main
    
    # Миграция всех коллекций
    python scripts/service/migrate_add_folders.py --all
    
    # Предпросмотр без изменений (dry-run)
    python scripts/service/migrate_add_folders.py --collection ksr_main --dry-run
    
    # Ускорение на мощном железе (больший размер батча)
    python scripts/service/migrate_add_folders.py --collection ksr_main --batch-size 64

Автор: Alexandr
Дата: 2025-12-03
"""

import os
import sys
import argparse
import logging
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple

import numpy as np
import torch
from tqdm import tqdm

# === НАСТРОЙКА ПУТЕЙ ДЛЯ ИМПОРТА ИЗ src/ ===
# Добавляем корень проекта в sys.path для импорта config
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Импорт конфигурации из проекта
from config import (
    QDRANT_STORAGE_PATH,
    QWEN_MODEL_PATH,
    EMBEDDING_BATCH_SIZE,
    UPLOAD_BATCH_SIZE,
)

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FolderMigrator:
    """
    Класс для миграции папок в существующие коллекции Qdrant.
    
    ВАЖНО: Работает напрямую с Qdrant без HTTP API сервера.
    Это позволяет использовать все ресурсы системы для максимальной скорости.
    
    Алгоритм работы:
    1. Подключается напрямую к Qdrant storage
    2. Получает все записи из коллекции через scroll API
    3. Извлекает уникальные папки из path_level_N полей
    4. Генерирует эмбеддинги для папок по full_path
    5. Загружает папки в коллекцию с is_folder=true и leaf_name
    """
    
    def __init__(self, embedding_batch_size: int = EMBEDDING_BATCH_SIZE):
        """
        Инициализация мигратора.
        
        Args:
            embedding_batch_size: Размер батча для генерации эмбеддингов
                                  (увеличьте для мощного GPU)
        """
        # Размер батча для эмбеддингов
        self.embedding_batch_size = embedding_batch_size
        
        # Ленивая загрузка моделей
        self.model = None
        self.tokenizer = None
        self.device = None
        
        # Инициализация Qdrant клиента
        self._init_qdrant_client()
        
    def _init_qdrant_client(self):
        """
        Инициализация прямого подключения к Qdrant.
        
        Использует локальное хранилище из config.py.
        Не требует запущенного сервера!
        """
        from qdrant_client import QdrantClient
        
        logger.info(f"🔌 Подключение к Qdrant: {QDRANT_STORAGE_PATH}")
        
        # Проверяем существование хранилища
        if not QDRANT_STORAGE_PATH.exists():
            logger.error(f"❌ Хранилище Qdrant не найдено: {QDRANT_STORAGE_PATH}")
            logger.error(f"💡 Сначала создайте коллекции через пайплайн")
            sys.exit(1)
        
        # Создаём клиент с прямым подключением к файлам
        self.client = QdrantClient(path=str(QDRANT_STORAGE_PATH))
        
        # Получаем список доступных коллекций
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        logger.info(f"✅ Подключено к Qdrant. Коллекции: {collection_names}")
        
    def _load_embedding_model(self):
        """
        Ленивая загрузка модели эмбеддингов.
        
        Загружается только при первом вызове генерации эмбеддингов.
        Использует Qwen3-Embedding-4B из config.py.
        """
        if self.model is not None:
            return
        
        logger.info(f"🔄 Загрузка модели эмбеддингов: {QWEN_MODEL_PATH}")
        
        from transformers import AutoTokenizer, AutoModel
        
        # Определяем устройство (CUDA если доступно)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🖥️ Устройство: {self.device}")
        
        if self.device == "cuda":
            # Показываем информацию о GPU
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
            logger.info(f"🎮 GPU: {gpu_name} ({gpu_memory:.1f} GB)")
        
        # Загрузка токенизатора
        self.tokenizer = AutoTokenizer.from_pretrained(
            QWEN_MODEL_PATH,
            padding_side="left",  # Важно для batch inference
            trust_remote_code=True
        )
        
        # Загрузка модели с оптимизациями
        self.model = AutoModel.from_pretrained(
            QWEN_MODEL_PATH,
            trust_remote_code=True,
            device_map=self.device,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        )
        self.model.eval()
        
        logger.info("✅ Модель эмбеддингов загружена")
    
    def _generate_embeddings(self, texts: List[str]) -> np.ndarray:
        """
        Генерация эмбеддингов для списка текстов.
        
        Использует last-token pooling и L2 нормализацию,
        как и основной сервер.
        
        Args:
            texts: Список текстов для эмбеддинга
            
        Returns:
            np.ndarray: Массив эмбеддингов (N x dimension)
        """
        # Ленивая загрузка модели
        self._load_embedding_model()
        
        all_embeddings = []
        batch_size = self.embedding_batch_size
        
        # Прогресс-бар для батчей
        total_batches = (len(texts) + batch_size - 1) // batch_size
        
        for i in tqdm(range(0, len(texts), batch_size), 
                      desc="🧠 Генерация эмбеддингов", 
                      total=total_batches):
            batch_texts = texts[i:i + batch_size]
            
            # Нормализация текстов (lowercase + strip)
            normalized_texts = [text.lower().strip() for text in batch_texts]
            
            # Токенизация
            inputs = self.tokenizer(
                normalized_texts,
                max_length=1024,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(self.device)
            
            # Генерация эмбеддингов без градиентов
            with torch.no_grad():
                outputs = self.model(**inputs)
            
            # === Last Token Pooling ===
            # Берём эмбеддинг последнего токена (как в Qwen3-Embedding)
            last_hidden_state = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"]
            
            # Проверяем направление паддинга
            left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
            
            if left_padding:
                # Left padding: последний токен всегда в конце
                embeddings = last_hidden_state[:, -1]
            else:
                # Right padding: нужно найти последний реальный токен
                sequence_lengths = attention_mask.sum(dim=1) - 1
                batch_size_local = last_hidden_state.shape[0]
                embeddings = last_hidden_state[
                    torch.arange(batch_size_local, device=last_hidden_state.device),
                    sequence_lengths,
                ]
            
            # L2 нормализация (для косинусного сходства)
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            
            # Сохраняем как float32 numpy array
            all_embeddings.append(embeddings.cpu().numpy().astype(np.float32))
            
            # Периодическая очистка памяти GPU
            if self.device == "cuda" and (i // batch_size) % 5 == 0:
                torch.cuda.empty_cache()
        
        return np.vstack(all_embeddings)
    
    def get_collections(self) -> List[str]:
        """
        Получение списка всех коллекций из Qdrant.
        
        Returns:
            List[str]: Список названий коллекций
        """
        collections = self.client.get_collections().collections
        return [c.name for c in collections]
    
    def get_all_records(self, collection_name: str) -> Dict[str, Dict]:
        """
        Получение всех записей из коллекции через scroll API.
        
        Использует пагинацию для эффективной работы с большими коллекциями.
        
        Args:
            collection_name: Название коллекции
            
        Returns:
            Dict[str, Dict]: Словарь {code: {payload данных}}
        """
        logger.info(f"📥 Получение записей из коллекции '{collection_name}'...")
        
        records = {}
        offset = None
        batch_size = 1000  # Размер страницы scroll
        
        # Получаем общее количество записей
        collection_info = self.client.get_collection(collection_name)
        total_points = collection_info.points_count
        logger.info(f"📊 Всего записей в коллекции: {total_points}")
        
        # Прогресс-бар
        pbar = tqdm(total=total_points, desc="📖 Чтение записей")
        
        while True:
            # Scroll API - эффективная пагинация
            points, next_offset = self.client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=True,
                with_vectors=False  # Векторы не нужны для анализа
            )
            
            # Обрабатываем записи
            for point in points:
                payload = point.payload or {}
                code = payload.get("code", str(point.id))
                records[code] = payload
            
            pbar.update(len(points))
            
            # Проверяем есть ли ещё данные
            if next_offset is None or len(points) == 0:
                break
            
            offset = next_offset
        
        pbar.close()
        logger.info(f"✅ Получено {len(records)} записей")
        return records
    
    def extract_folders(self, records: Dict[str, Dict], separator: str = "→") -> List[Dict]:
        """
        Извлечение уникальных папок из записей материалов.
        
        Создаёт папки для КАЖДОГО уровня иерархии.
        Например, для материала "Арматура → Задвижки → Клиновые"
        создаются папки:
        - "Арматура" (level 1)
        - "Арматура → Задвижки" (level 2)
        - "Арматура → Задвижки → Клиновые" (level 3)
        
        Args:
            records: Словарь записей из коллекции
            separator: Разделитель для формирования пути
            
        Returns:
            List[Dict]: Список уникальных папок с метаданными
        """
        logger.info("📁 Извлечение уникальных папок из записей...")
        
        # Словарь для подсчёта папок: tuple(path_parts) -> count
        folder_counts: Dict[Tuple[str, ...], Dict] = {}
        
        # Счётчики для статистики
        materials_count = 0
        folders_skipped = 0
        
        for code, record in records.items():
            # Пропускаем существующие папки (is_folder=true)
            if record.get("is_folder"):
                folders_skipped += 1
                continue
            
            materials_count += 1
            
            # Получаем глубину пути
            path_depth = record.get("path_depth", 0)
            if path_depth == 0:
                continue
            
            # Собираем части пути из path_level_N
            path_parts = []
            for level in range(1, path_depth + 1):
                level_key = f"path_level_{level}"
                if level_key in record and record[level_key]:
                    path_parts.append(record[level_key])
                else:
                    break  # Прерываем при отсутствии уровня
            
            # Создаём папки для КАЖДОГО уровня иерархии
            for level in range(1, len(path_parts) + 1):
                current_parts = tuple(path_parts[:level])
                
                if current_parts not in folder_counts:
                    folder_counts[current_parts] = {
                        "count": 0,
                        "parts": list(current_parts)
                    }
                
                folder_counts[current_parts]["count"] += 1
        
        logger.info(f"📊 Обработано материалов: {materials_count}")
        logger.info(f"⏭️ Пропущено папок (уже существуют): {folders_skipped}")
        
        # Формируем результат с полными метаданными
        folders = []
        for path_tuple, data in folder_counts.items():
            parts = data["parts"]
            level = len(parts)
            
            # Полный путь (для эмбеддинга)
            full_path = f" {separator} ".join(parts)
            
            # Название конечной папки (для rerank)
            leaf_name = parts[-1] if parts else ""
            
            # Формируем path_levels для payload
            path_levels = {}
            for i, part in enumerate(parts):
                path_levels[f"path_level_{i + 1}"] = part
            
            folders.append({
                "full_path": full_path,
                "leaf_name": leaf_name,
                "level": level,
                "items_count": data["count"],
                "path_levels": path_levels
            })
        
        # Сортируем по уровню и пути
        folders.sort(key=lambda x: (x["level"], x["full_path"]))
        
        logger.info(f"✅ Извлечено {len(folders)} уникальных папок")
        return folders
    
    def check_existing_folders(self, collection_name: str) -> int:
        """
        Проверка количества существующих папок в коллекции.
        
        Использует фильтр is_folder=true для подсчёта.
        
        Args:
            collection_name: Название коллекции
            
        Returns:
            int: Количество папок с is_folder=true
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        try:
            # Фильтр для поиска папок
            folder_filter = Filter(
                must=[
                    FieldCondition(
                        key="is_folder",
                        match=MatchValue(value=True)
                    )
                ]
            )
            
            # Считаем количество папок
            count_result = self.client.count(
                collection_name=collection_name,
                count_filter=folder_filter,
                exact=True
            )
            
            return count_result.count
            
        except Exception as e:
            logger.warning(f"⚠️ Не удалось проверить существующие папки: {e}")
            return 0
    
    def upload_folders(
        self, 
        collection_name: str, 
        folders: List[Dict]
    ) -> int:
        """
        Загрузка папок в коллекцию напрямую через Qdrant client.
        
        Args:
            collection_name: Название коллекции
            folders: Список папок для загрузки
            
        Returns:
            int: Количество загруженных папок
        """
        from qdrant_client.models import PointStruct
        
        if not folders:
            logger.info("📁 Нет папок для загрузки")
            return 0
        
        logger.info(f"📤 Загрузка {len(folders)} папок в коллекцию '{collection_name}'...")
        
        # === ШАГ 1: Генерация эмбеддингов ===
        folder_texts = [f["full_path"] for f in folders]
        embeddings = self._generate_embeddings(folder_texts)
        logger.info(f"✅ Сгенерировано {len(embeddings)} эмбеддингов")
        
        # === ШАГ 2: Формирование точек для Qdrant ===
        points = []
        timestamp = time.time()
        
        for folder, emb in zip(folders, embeddings):
            # Уникальный код папки
            folder_code = f"folder::{folder['full_path'].replace(' → ', '::')}"
            
            # Детерминированный UUID на основе кода
            folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
            
            # Payload с метаданными папки
            payload = {
                "code": folder_code,
                "description": folder["full_path"],
                "full_path": folder["full_path"],
                "leaf_name": folder["leaf_name"],
                "path_depth": folder["level"],
                "items_count": folder["items_count"],
                "is_folder": True,  # КЛЮЧЕВОЙ флаг!
                "timestamp": timestamp,
                "source": "migration_add_folders",
                **folder["path_levels"]  # path_level_1, path_level_2, ...
            }
            
            points.append(PointStruct(
                id=folder_id,
                vector=emb.tolist(),
                payload=payload
            ))
        
        # === ШАГ 3: Загрузка батчами ===
        uploaded = 0
        upload_batch_size = UPLOAD_BATCH_SIZE
        
        for i in tqdm(range(0, len(points), upload_batch_size), 
                      desc="📦 Загрузка папок"):
            batch = points[i:i + upload_batch_size]
            
            try:
                # Upsert - обновляет существующие или создаёт новые
                self.client.upsert(
                    collection_name=collection_name,
                    points=batch
                )
                uploaded += len(batch)
                
            except Exception as e:
                logger.error(f"❌ Ошибка загрузки батча: {e}")
        
        logger.info(f"✅ Загружено {uploaded} папок")
        return uploaded
    
    def migrate_collection(
        self, 
        collection_name: str, 
        dry_run: bool = False,
        force: bool = False
    ) -> Dict:
        """
        Миграция коллекции - добавление индексированных папок.
        
        Args:
            collection_name: Название коллекции
            dry_run: Только анализ без изменений
            force: Принудительная миграция даже если папки уже есть
            
        Returns:
            Dict: Статистика миграции
        """
        logger.info("=" * 80)
        logger.info(f"📁 МИГРАЦИЯ КОЛЛЕКЦИИ: {collection_name}")
        logger.info("=" * 80)
        
        # Статистика миграции
        stats = {
            "collection": collection_name,
            "status": "success",
            "existing_folders": 0,
            "extracted_folders": 0,
            "uploaded_folders": 0,
            "skipped": False
        }
        
        # Проверяем существование коллекции
        available_collections = self.get_collections()
        if collection_name not in available_collections:
            logger.error(f"❌ Коллекция '{collection_name}' не найдена!")
            logger.error(f"💡 Доступные коллекции: {available_collections}")
            stats["status"] = "error"
            return stats
        
        # Проверяем существующие папки
        existing_count = self.check_existing_folders(collection_name)
        stats["existing_folders"] = existing_count
        
        if existing_count > 0 and not force:
            logger.info(f"ℹ️ Коллекция уже содержит {existing_count} папок")
            logger.info("💡 Используйте --force для принудительной миграции")
            stats["skipped"] = True
            return stats
        
        # Получаем все записи
        records = self.get_all_records(collection_name)
        
        if not records:
            logger.warning(f"⚠️ Коллекция '{collection_name}' пуста")
            stats["status"] = "error"
            return stats
        
        # Извлекаем папки
        folders = self.extract_folders(records)
        stats["extracted_folders"] = len(folders)
        
        if not folders:
            logger.info("📁 Папки не найдены (нет иерархии в данных)")
            return stats
        
        # === DRY-RUN режим ===
        if dry_run:
            logger.info("\n" + "=" * 80)
            logger.info("🔍 DRY-RUN: Изменения НЕ будут применены")
            logger.info("=" * 80)
            
            logger.info(f"\n📊 Найдено папок: {len(folders)}")
            
            # Статистика по уровням
            level_stats = {}
            for folder in folders:
                level = folder["level"]
                level_stats[level] = level_stats.get(level, 0) + 1
            
            logger.info("\n📈 Распределение по уровням:")
            for level in sorted(level_stats.keys()):
                logger.info(f"   Уровень {level}: {level_stats[level]} папок")
            
            logger.info("\n📋 Примеры папок (первые 15):")
            for folder in folders[:15]:
                logger.info(f"   📁 {folder['full_path']}")
                logger.info(f"      leaf_name: '{folder['leaf_name']}', "
                          f"level: {folder['level']}, items: {folder['items_count']}")
            
            if len(folders) > 15:
                logger.info(f"   ... и еще {len(folders) - 15} папок")
            
            logger.info("=" * 80)
            return stats
        
        # === РЕАЛЬНАЯ МИГРАЦИЯ ===
        uploaded = self.upload_folders(collection_name, folders)
        stats["uploaded_folders"] = uploaded
        
        # Итоговый отчёт
        logger.info("=" * 80)
        logger.info("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
        logger.info("=" * 80)
        logger.info(f"📊 Извлечено папок: {stats['extracted_folders']}")
        logger.info(f"📤 Загружено папок: {stats['uploaded_folders']}")
        logger.info("=" * 80)
        
        return stats


def main():
    """Основная функция скрипта"""
    
    parser = argparse.ArgumentParser(
        description="Миграция: добавление индексированных папок в коллекции Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Предпросмотр изменений
  python scripts/service/migrate_add_folders.py --collection ksr_main --dry-run
  
  # Миграция коллекции
  python scripts/service/migrate_add_folders.py --collection ksr_main
  
  # Миграция с ускорением на мощном GPU
  python scripts/service/migrate_add_folders.py --collection ksr_main --batch-size 64
  
  # Миграция всех коллекций
  python scripts/service/migrate_add_folders.py --all
        """
    )
    
    parser.add_argument(
        "--collection",
        type=str,
        help="Название коллекции для миграции"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Мигрировать все коллекции"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только анализ без изменений"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Принудительная миграция даже если папки уже есть"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=EMBEDDING_BATCH_SIZE,
        help=f"Размер батча для генерации эмбеддингов (default: {EMBEDDING_BATCH_SIZE}). "
             f"Увеличьте для мощного GPU (например, 64 или 128)"
    )
    
    args = parser.parse_args()
    
    # Проверка аргументов
    if not args.collection and not args.all:
        parser.error("Укажите --collection <name> или --all")
    
    # === НАЧАЛО РАБОТЫ ===
    start_time = time.time()
    
    logger.info("=" * 80)
    logger.info("🚀 МИГРАЦИЯ: ДОБАВЛЕНИЕ ИНДЕКСИРОВАННЫХ ПАПОК")
    logger.info("=" * 80)
    logger.info(f"💾 Хранилище Qdrant: {QDRANT_STORAGE_PATH}")
    logger.info(f"🧠 Модель эмбеддингов: {QWEN_MODEL_PATH}")
    logger.info(f"📦 Размер батча: {args.batch_size}")
    logger.info(f"🔍 Режим: {'DRY-RUN (только анализ)' if args.dry_run else 'РЕАЛЬНАЯ МИГРАЦИЯ'}")
    logger.info(f"💪 Force: {'Да' if args.force else 'Нет'}")
    logger.info("=" * 80)
    
    try:
        # Создаём мигратор
        migrator = FolderMigrator(embedding_batch_size=args.batch_size)
        
        # Определяем коллекции для миграции
        if args.all:
            collections = migrator.get_collections()
            logger.info(f"📚 Найдено коллекций: {len(collections)}")
        else:
            collections = [args.collection]
        
        # Миграция каждой коллекции
        all_stats = []
        
        for collection in collections:
            stats = migrator.migrate_collection(
                collection_name=collection,
                dry_run=args.dry_run,
                force=args.force
            )
            all_stats.append(stats)
        
        # === ИТОГОВАЯ СТАТИСТИКА ===
        logger.info("\n" + "=" * 80)
        logger.info("📊 ИТОГОВАЯ СТАТИСТИКА")
        logger.info("=" * 80)
        
        total_extracted = sum(s["extracted_folders"] for s in all_stats)
        total_uploaded = sum(s["uploaded_folders"] for s in all_stats)
        total_skipped = sum(1 for s in all_stats if s.get("skipped"))
        total_errors = sum(1 for s in all_stats if s.get("status") == "error")
        
        logger.info(f"📚 Коллекций обработано: {len(collections)}")
        logger.info(f"⏭️ Пропущено (уже мигрированы): {total_skipped}")
        logger.info(f"❌ Ошибок: {total_errors}")
        logger.info(f"📁 Всего папок извлечено: {total_extracted}")
        logger.info(f"📤 Всего папок загружено: {total_uploaded}")
        logger.info(f"⏱️ Время выполнения: {time.time() - start_time:.2f} сек")
        logger.info("=" * 80)
        
        # Подсказка после миграции
        if total_uploaded > 0:
            logger.info("\n💡 СЛЕДУЮЩИЕ ШАГИ:")
            logger.info("   1. Запустите сервер: python src/server.py")
            logger.info("   2. Проверьте поиск по папкам в веб-интерфейсе")
            logger.info("   3. При необходимости очистите кэш иерархии через API")
        
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
