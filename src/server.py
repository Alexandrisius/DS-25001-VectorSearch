# server.py - ВЕРСИЯ С QDRANT ВЕКТОРНОЙ БД
"""
Backend-сервер для семантического поиска по КСР (Классификатор Строительных Ресурсов).

Основные функции:
1.  **Векторный поиск (Stage 1)**: Использует Qdrant для быстрого поиска кандидатов по косинусному сходству.
2.  **Переранжирование (Stage 2)**: Использует Cross-Encoder (BGE-M3) для точного ранжирования топ-кандидатов.
3.  **Генерация эмбеддингов**: Использует локальную модель Qwen3-Embedding-4B.
4.  **Управление данными**: API для обновления, удаления и добавления записей.
5.  **Аналитика**: Сбор статистики использования (копирование, дизлайки).

Архитектура:
-   **FastAPI**: Асинхронный веб-фреймворк.
-   **Qdrant**: Векторная база данных (Local mode).
-   **Transformers/Sentence-Transformers**: ML-модели.
-   **ThreadPoolExecutor**: Для выполнения тяжелых CPU-задач без блокировки Event Loop.

Автор: Alexandr
Дата обновления: 29.11.2025
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import torch
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    MatchAny,
    PointStruct,
    VectorParams,
)
from sentence_transformers import CrossEncoder
from transformers import AutoModel, AutoTokenizer

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# === УТИЛИТЫ ДЛЯ ИЕРАРХИЧЕСКОГО КАТАЛОГА ===
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

# === Импорт конфигурации ===
# Все пути и настройки вынесены в отдельный файл config.py
from config import (
    PROJECT_ROOT,
    QDRANT_STORAGE_PATH,
    INTERIM_DATA_DIR as DATA_DIR,
    WEB_DIR,
    QWEN_MODEL_PATH,
    RERANKER_PATH,
    VECTOR_DATABASES_CONFIG,
    FEEDBACK_DIR,
    EMBEDDING_CACHE_SIZE,
    SERVER_HOST,
    SERVER_PORT,
)

# Базовая директория скрипта (для обратной совместимости)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# === ОПТИМИЗАЦИЯ: Кэш для эмбеддингов ===
class EmbeddingCache:
    """
    LRU-кэш (Least Recently Used) для хранения сгенерированных эмбеддингов запросов.
    
    Позволяет существенно ускорить обработку повторяющихся запросов, избегая 
    повторного инференса тяжелой нейросети.
    
    Attributes:
        cache (dict): Словарь хранения {текст: вектор}.
        max_size (int): Максимальное количество элементов в кэше.
        access_times (dict): Словарь времени последнего доступа для LRU-логики.
        lock (asyncio.Lock): Асинхронный мьютекс для потокобезопасности.
    """

    def __init__(self, max_size=10000):
        """
        Инициализация кэша.

        Args:
            max_size (int): Лимит записей. По умолчанию 10000.
        """
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
        self.lock = asyncio.Lock()

    async def get(self, text: str) -> Optional[np.ndarray]:
        """
        Получение эмбеддинга из кэша.
        
        Ключ автоматически нормализуется (lowercase + strip).
        Обновляет время последнего доступа (LRU).

        Args:
            text (str): Текст запроса.

        Returns:
            Optional[np.ndarray]: Вектор эмбеддинга или None, если не найден.
        """
        async with self.lock:
            key = text.lower().strip()  # Нормализация ключа
            if key in self.cache:
                self.access_times[key] = time.time()
                return self.cache[key]
            return None

    async def set(self, text: str, embedding: np.ndarray):
        """
        Сохранение эмбеддинга в кэш.
        
        Если кэш переполнен, удаляет наименее используемый элемент (LRU).

        Args:
            text (str): Текст запроса.
            embedding (np.ndarray): Вектор эмбеддинга.
        """
        async with self.lock:
            key = text.lower().strip()  # Нормализация ключа
            if len(self.cache) >= self.max_size:
                # Удаляем самый старый элемент (LRU)
                oldest_key = min(self.access_times, key=self.access_times.get)
                del self.cache[oldest_key]
                del self.access_times[oldest_key]
            self.cache[key] = embedding.copy()
            self.access_times[key] = time.time()

    def clear(self):
        """Очистка кэша"""
        self.cache.clear()
        self.access_times.clear()
        logger.info("🧹 Кэш эмбеддингов очищен")


# === СЕРВИС ИЕРАРХИЧЕСКОГО КАТАЛОГА ===
class HierarchyService:
    """
    Сервис для построения и кэширования дерева иерархии категорий.
    
    Использует поля path_level_N из Qdrant для построения навигационного
    дерева категорий. Результаты кэшируются для производительности.
    
    Attributes:
        cache (dict): Кэш деревьев {collection_name: {tree, timestamp, stats}}.
        cache_ttl (int): Время жизни кэша в секундах (по умолчанию 300 = 5 минут).
    """
    
    def __init__(self, cache_ttl: int = 300):
        """
        Инициализация сервиса.
        
        Args:
            cache_ttl (int): Время жизни кэша в секундах.
        """
        self.cache = {}  # Кэш полного дерева {collection_name: {tree, stats, timestamp}}
        self.children_cache = {}  # Кэш прямых детей {cache_key: {children, timestamp}}
        self.cache_ttl = cache_ttl
        self.lock = asyncio.Lock()
    
    def _is_cache_valid(self, collection_name: str) -> bool:
        """
        Проверка актуальности кэша для коллекции.
        
        Args:
            collection_name: Имя коллекции.
            
        Returns:
            bool: True если кэш актуален.
        """
        if collection_name not in self.cache:
            return False
        
        cache_entry = self.cache[collection_name]
        age = time.time() - cache_entry["timestamp"]
        return age < self.cache_ttl
    
    async def get_hierarchy(
        self,
        client: QdrantClient,
        collection_name: str,
        separator: str = "→",
        max_depth: int = 10
    ) -> dict:
        """
        Получение дерева иерархии для коллекции.
        
        Если кэш актуален, возвращает кэшированное дерево.
        Иначе строит новое дерево через scroll API Qdrant.
        
        Args:
            client: Клиент Qdrant.
            collection_name: Имя коллекции.
            separator: Разделитель уровней (для отображения).
            max_depth: Максимальная глубина дерева.
            
        Returns:
            dict: Структура {tree: [...], total_categories: N, cached: bool}.
        """
        async with self.lock:
            # Проверяем кэш
            if self._is_cache_valid(collection_name):
                logger.info(f"📦 Hierarchy cache hit: {collection_name}")
                cached = self.cache[collection_name]
                return {
                    "tree": cached["tree"],
                    "total_categories": cached["stats"]["total_categories"],
                    "total_items": cached["stats"]["total_items"],
                    "max_depth": cached["stats"]["max_depth"],
                    "cached": True,
                    "cache_age": int(time.time() - cached["timestamp"])
                }
            
            # Строим новое дерево
            logger.info(f"🌳 Building hierarchy tree for: {collection_name}")
            start_time = time.time()
            
            tree_data = await self._build_tree(
                client, collection_name, separator, max_depth
            )
            
            # Сохраняем в кэш
            self.cache[collection_name] = {
                "tree": tree_data["tree"],
                "stats": tree_data["stats"],
                "timestamp": time.time()
            }
            
            elapsed = time.time() - start_time
            logger.info(
                f"✅ Hierarchy built in {elapsed:.2f}s: "
                f"{tree_data['stats']['total_categories']} categories"
            )
            
            return {
                "tree": tree_data["tree"],
                "total_categories": tree_data["stats"]["total_categories"],
                "total_items": tree_data["stats"]["total_items"],
                "max_depth": tree_data["stats"]["max_depth"],
                "cached": False,
                "build_time": elapsed
            }
    
    async def _build_tree(
        self,
        client: QdrantClient,
        collection_name: str,
        separator: str,
        max_depth: int
    ) -> dict:
        """
        Построение дерева иерархии из записей коллекции.
        
        Алгоритм:
        1. Scroll по всем записям, собирая path_level_N значения и коды.
        2. Агрегация уникальных путей, подсчёт количества и сохранение кодов.
        3. Рекурсивное построение дерева из агрегированных данных.
        
        Args:
            client: Клиент Qdrant.
            collection_name: Имя коллекции.
            separator: Разделитель уровней.
            max_depth: Максимальная глубина.
            
        Returns:
            dict: {tree: [...], stats: {...}}.
        """
        # Словарь для агрегации: {(level, path): {"count": N, "codes": [...]}}
        # Сохраняем коды для листовых элементов
        path_data = {}
        total_items = 0
        max_found_depth = 0
        
        # Scroll по всем записям
        offset = None
        batch_size = 1000
        
        while True:
            # Запрашиваем path_level_N, path_depth и код
            payload_fields = [f"path_level_{i}" for i in range(1, max_depth + 1)]
            payload_fields.extend(["path_depth", "code", "description"])
            
            records, next_offset = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                with_payload=payload_fields,
                with_vectors=False
            )
            
            if not records:
                break
            
            for point in records:
                total_items += 1
                payload = point.payload
                
                # Получаем глубину записи и код
                depth = payload.get("path_depth", 1)
                code = payload.get("code", "")
                max_found_depth = max(max_found_depth, depth)
                
                # Собираем все уровни пути
                for level in range(1, min(depth + 1, max_depth + 1)):
                    path_key = f"path_level_{level}"
                    path_value = payload.get(path_key)
                    
                    if path_value:
                        # Формируем ключ для агрегации: (level, path)
                        agg_key = (level, path_value)
                        
                        if agg_key not in path_data:
                            path_data[agg_key] = {"count": 0, "codes": [], "is_leaf": False}
                        
                        path_data[agg_key]["count"] += 1
                        
                        # Для максимального уровня (листа) сохраняем код
                        if level == depth and code:
                            # Ограничиваем количество сохраняемых кодов
                            if len(path_data[agg_key]["codes"]) < 10:
                                path_data[agg_key]["codes"].append(code)
                            path_data[agg_key]["is_leaf"] = True
            
            offset = next_offset
            if offset is None:
                break
        
        # Строим дерево из агрегированных данных
        tree = self._build_tree_structure(path_data, separator, max_depth)
        
        # Подсчёт статистики
        total_categories = len(set(path for (level, path) in path_data.keys()))
        
        return {
            "tree": tree,
            "stats": {
                "total_categories": total_categories,
                "total_items": total_items,
                "max_depth": max_found_depth
            }
        }
    
    def _build_tree_structure(
        self,
        path_data: dict,
        separator: str,
        max_depth: int
    ) -> List[dict]:
        """
        Построение древовидной структуры из плоского словаря путей.
        
        Args:
            path_data: Словарь {(level, path): {"count": N, "codes": [...], "is_leaf": bool}}.
            separator: Разделитель уровней.
            max_depth: Максимальная глубина.
            
        Returns:
            List[dict]: Список корневых узлов дерева.
        """
        # Группируем по уровням
        levels = {}
        for (level, path), data in path_data.items():
            if level not in levels:
                levels[level] = {}
            levels[level][path] = data
        
        if not levels:
            return []
        
        # Строим дерево рекурсивно начиная с уровня 1
        def build_children(parent_path: str, current_level: int) -> List[dict]:
            """Рекурсивное построение детей для узла."""
            if current_level > max_depth:
                return []
            
            next_level = current_level + 1
            children = []
            
            if next_level not in levels:
                return []
            
            # Ищем детей: пути следующего уровня, начинающиеся с parent_path
            for path, data in levels[next_level].items():
                # Проверяем, что путь начинается с родительского
                if path.startswith(parent_path + f" {separator} "):
                    # Извлекаем имя текущего узла (последний сегмент)
                    parts = path.split(f" {separator} ")
                    name = parts[-1] if parts else path
                    
                    node = {
                        "name": name,
                        "path": path,
                        "level": next_level,
                        "count": data["count"],
                        "children": build_children(path, next_level)
                    }
                    
                    # Добавляем код для листовых элементов (count=1 или is_leaf)
                    if data["is_leaf"] and data["codes"]:
                        if data["count"] == 1 and len(data["codes"]) == 1:
                            # Точно один элемент - показываем код
                            node["code"] = data["codes"][0]
                        elif len(data["codes"]) > 0:
                            # Несколько элементов - показываем первые коды
                            node["codes"] = data["codes"][:5]
                    
                    children.append(node)
            
            # Сортируем по имени
            children.sort(key=lambda x: x["name"])
            return children
        
        # Строим корневые узлы (уровень 1)
        root_nodes = []
        
        if 1 in levels:
            for path, data in levels[1].items():
                node = {
                    "name": path,  # На первом уровне имя = путь
                    "path": path,
                    "level": 1,
                    "count": data["count"],
                    "children": build_children(path, 1)
                }
                
                # Добавляем код для листовых элементов
                if data["is_leaf"] and data["codes"]:
                    if data["count"] == 1 and len(data["codes"]) == 1:
                        node["code"] = data["codes"][0]
                    elif len(data["codes"]) > 0:
                        node["codes"] = data["codes"][:5]
                
                root_nodes.append(node)
        
        # Сортируем корневые узлы по имени
        root_nodes.sort(key=lambda x: x["name"])
        
        return root_nodes
    
    def invalidate_cache(self, collection_name: Optional[str] = None):
        """
        Инвалидация кэша иерархии.
        
        Args:
            collection_name: Имя коллекции для инвалидации.
                            Если None - очищает весь кэш.
        """
        if collection_name:
            if collection_name in self.cache:
                del self.cache[collection_name]
                logger.info(f"🗑️ Hierarchy cache invalidated: {collection_name}")
            # Также очищаем кэш прямых детей для этой коллекции
            keys_to_delete = [k for k in self.children_cache.keys() if k.startswith(f"{collection_name}_")]
            for key in keys_to_delete:
                del self.children_cache[key]
            if keys_to_delete:
                logger.info(f"🗑️ Children cache invalidated: {len(keys_to_delete)} entries for {collection_name}")
        else:
            self.cache.clear()
            self.children_cache.clear()
            logger.info("🗑️ Hierarchy cache cleared (all collections)")
    
    async def get_children_direct(
        self,
        client: QdrantClient,
        collection_name: str,
        parent_path: str = "",
        parent_level: int = 0,
        separator: str = "→"
    ) -> dict:
        """
        Прямое получение дочерних категорий без построения полного дерева.
        
        Использует scroll API Qdrant с фильтром по родительскому пути.
        Группирует результаты по следующему уровню для подсчёта.
        
        ОПТИМИЗАЦИЯ: Не строит полное дерево! Загружает только нужный уровень.
        
        Args:
            client: Клиент Qdrant.
            collection_name: Имя коллекции.
            parent_path: Путь родительской категории (пустой = корень).
            parent_level: Уровень родителя (0 = корень, дети будут уровня 1).
            separator: Разделитель уровней.
            
        Returns:
            dict: {children: [...], parent_path: str, total: int, cached: bool}
        """
        # Ключ кэша включает путь родителя
        cache_key = f"{collection_name}_children_{parent_level}_{parent_path}"
        
        # Проверяем кэш прямых детей (TTL 5 минут)
        if cache_key in self.children_cache:
            cache_entry = self.children_cache[cache_key]
            age = time.time() - cache_entry["timestamp"]
            if age < self.cache_ttl:
                logger.debug(f"📦 Children cache hit: {cache_key[:50]}...")
                return {
                    "children": cache_entry["children"],
                    "parent_path": parent_path,
                    "total": len(cache_entry["children"]),
                    "cached": True,
                    "cache_age": int(age)
                }
        
        # Уровень детей = уровень родителя + 1
        child_level = parent_level + 1
        child_level_field = f"path_level_{child_level}"
        
        logger.info(f"🔍 Direct children load: parent='{parent_path[:50]}...' level={child_level}")
        start_time = time.time()
        
        # Словарь для агрегации детей: {path: {count, codes, has_children}}
        children_data = {}
        
        # Формируем фильтр
        scroll_filter = None
        if parent_path:
            # Фильтруем по точному значению родительского пути
            parent_level_field = f"path_level_{parent_level}"
            scroll_filter = Filter(
                must=[
                    FieldCondition(
                        key=parent_level_field,
                        match=MatchValue(value=parent_path)
                    )
                ]
            )
        
        # Scroll по записям
        offset = None
        batch_size = 1000
        total_scanned = 0
        
        while True:
            # Запрашиваем только нужные поля
            payload_fields = [child_level_field, f"path_level_{child_level + 1}", "code", "path_depth"]
            
            records, next_offset = client.scroll(
                collection_name=collection_name,
                limit=batch_size,
                offset=offset,
                scroll_filter=scroll_filter,
                with_payload=payload_fields,
                with_vectors=False
            )
            
            if not records:
                break
            
            total_scanned += len(records)
            
            for point in records:
                payload = point.payload
                
                # Получаем путь на уровне детей
                child_path = payload.get(child_level_field)
                if not child_path:
                    continue
                
                # Агрегируем данные
                if child_path not in children_data:
                    children_data[child_path] = {
                        "count": 0,
                        "codes": [],
                        "has_children": False
                    }
                
                children_data[child_path]["count"] += 1
                
                # Проверяем наличие следующего уровня (есть ли дети)
                next_level_path = payload.get(f"path_level_{child_level + 1}")
                if next_level_path:
                    children_data[child_path]["has_children"] = True
                
                # Собираем коды для листовых элементов
                code = payload.get("code")
                depth = payload.get("path_depth", 1)
                if code and depth == child_level and len(children_data[child_path]["codes"]) < 5:
                    children_data[child_path]["codes"].append(code)
            
            offset = next_offset
            if offset is None:
                break
        
        # Формируем список детей
        children = []
        for path, data in children_data.items():
            # Извлекаем имя (последний сегмент пути)
            parts = path.split(f" {separator} ")
            name = parts[-1] if parts else path
            
            child = {
                "name": name,
                "path": path,
                "level": child_level,
                "count": data["count"],
                "has_children": data["has_children"]
            }
            
            # Добавляем код/коды если есть
            if data["codes"]:
                if data["count"] == 1 and len(data["codes"]) == 1:
                    child["code"] = data["codes"][0]
                else:
                    child["codes"] = data["codes"]
            
            children.append(child)
        
        # Сортируем по имени
        children.sort(key=lambda x: x["name"])
        
        elapsed = time.time() - start_time
        logger.info(
            f"✅ Direct children loaded in {elapsed:.2f}s: "
            f"{len(children)} children, scanned {total_scanned} records"
        )
        
        # Сохраняем в кэш
        self.children_cache[cache_key] = {
            "children": children,
            "timestamp": time.time()
        }
        
        return {
            "children": children,
            "parent_path": parent_path,
            "total": len(children),
            "cached": False,
            "load_time": elapsed
        }


# === МЕНЕДЖЕР ВЕКТОРНЫХ БАЗ НА ОСНОВЕ QDRANT ===
class QdrantVectorDatabaseManager:
    """
    Менеджер для управления векторными базами данных Qdrant и моделями ML.

    Этот класс инкапсулирует всю логику работы с данными:
    1.  Инициализация и хранение подключения к Qdrant.
    2.  Загрузка и инференс моделей (Embedding & Reranker).
    3.  Управление конфигурациями коллекций (Hot Reload).
    4.  Выполнение поисковых запросов и CRUD операций.

    Attributes:
        storage_path (str): Путь к локальному хранилищу Qdrant.
        executor (ThreadPoolExecutor): Пул потоков для выполнения блокирующих операций.
        device (str): Устройство вычислений ('cuda' или 'cpu').
        client (QdrantClient): Клиент для взаимодействия с БД.
        embedding_model (AutoModel): Загруженная модель трансформера.
        tokenizer (AutoTokenizer): Токенизатор для модели.
        collections_metadata (dict): Кэш метаданных активных коллекций.
    """

    def __init__(self, storage_path: str):
        """
        Инициализация менеджера.

        Запускает пул потоков, определяет устройство (GPU/CPU),
        подключается к Qdrant и загружает конфигурацию.

        Args:
            storage_path (str): Абсолютный путь к директории с данными Qdrant.
        """
        self.storage_path = storage_path
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Определение устройства для вычислений (CPU/CUDA)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"🖥️ Устройство для вычислений: {self.device}")

        # КРИТИЧНО: Сохраняем путь к конфигу для перезагрузки
        # Используем путь из централизованной конфигурации (config.py)
        self.config_path = str(VECTOR_DATABASES_CONFIG)
        
        # GPU Lock для защиты памяти при параллельных запросах
        self.gpu_lock = asyncio.Lock()

        # Путь к файлу отложенных удалений
        self.pending_deletions_path = storage_path / "pending_deletions.json"
        
        # Очищаем отложенные удаления ПЕРЕД подключением к Qdrant
        # (пока файлы ещё не заблокированы)
        self._cleanup_pending_deletions()
        
        # Инициализация Qdrant клиента
        logger.info(f"🔌 Подключение к Qdrant: {storage_path}")
        self.client = QdrantClient(path=storage_path)

        # Словарь метаданных коллекций {название: метаданные}
        self.collections_metadata = {}

        # Загрузка конфигурации баз из JSON
        self.load_configuration()

        # Текущая активная коллекция
        self.current_collection = (
            next(iter(self.collections_metadata)) if self.collections_metadata else None
        )

        if self.current_collection:
            logger.info(f"🎯 Активная коллекция: {self.current_collection}")
        else:
            logger.warning("⚠️ Нет доступных коллекций в Qdrant")

        # === ИНИЦИАЛИЗАЦИЯ МОДЕЛИ ЭМБЕДДИНГОВ ===
        self._init_embedding_model()
        
        # Инициализация кэша
        # Размер кэша определён в config.py (EMBEDDING_CACHE_SIZE)
        self.embedding_cache = EmbeddingCache(max_size=EMBEDDING_CACHE_SIZE)

    def _init_embedding_model(self):
        """
        Загрузка модели эмбеддингов (Qwen) в память.
        
        Использует библиотеку `transformers`. Модель загружается в режиме `eval` (inference only).
        Если доступна CUDA, используется FP16 для экономии видеопамяти и ускорения.
        """
        logger.info(f"📥 Загрузка модели эмбеддингов: {QWEN_MODEL_PATH}")
        
        self.tokenizer = AutoTokenizer.from_pretrained(
            QWEN_MODEL_PATH, padding_side="left", trust_remote_code=True
        )

        self.embedding_model = AutoModel.from_pretrained(
            QWEN_MODEL_PATH,
            trust_remote_code=True,
            device_map=self.device,
            torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
        )
        self.embedding_model.eval()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        logger.info("✅ Модель эмбеддингов загружена")

    def get_embeddings_batch(self, texts: List[str], batch_size: int = 8) -> np.ndarray:
        """
        Генерация эмбеддингов для списка текстов (Batch Inference).

        Оптимизирована для GPU: обрабатывает данные пакетами (batch_size),
        чтобы эффективно использовать параллелизм CUDA ядер.
        
        Args:
            texts (List[str]): Список исходных текстов.
            batch_size (int): Размер пакета (default: 8).
            
        Returns:
            np.ndarray: Массив векторов размерности (N, D), где N - кол-во текстов, D - размерность модели.
        """
        all_embeddings = []
        
        # Разбиваем на мини-батчи
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            # Нормализация
            batch_texts = [t.lower().strip() for t in batch_texts]
            
            try:
                inputs = self.tokenizer(
                    batch_texts,
                    max_length=1024,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                ).to(self.device)
                
                with torch.no_grad():
                    outputs = self.embedding_model(**inputs)
                    
                last_hidden_state = outputs.last_hidden_state
                attention_mask = inputs["attention_mask"]
                
                # Last token pooling logic
                left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
                if left_padding:
                    embeddings = last_hidden_state[:, -1]
                else:
                    sequence_lengths = attention_mask.sum(dim=1) - 1
                    batch_indices = torch.arange(last_hidden_state.shape[0], device=last_hidden_state.device)
                    embeddings = last_hidden_state[batch_indices, sequence_lengths]
                    
                embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
                all_embeddings.append(embeddings.cpu().numpy().astype(np.float32))
                
            except Exception as e:
                logger.error(f"Ошибка в батче эмбеддингов: {e}")
                # Fallback: пустые векторы или повторная попытка по одному
                raise e
                
        if not all_embeddings:
            return np.array([])
            
        return np.vstack(all_embeddings)

    def save_configuration(self):
        """
        Сохранение текущей конфигурации в JSON файл.
        Вызывается после любых изменений в настройках или списке баз.
        """
        try:
            config = {}
            for name, meta in self.collections_metadata.items():
                config[name] = {
                    "description": meta.get("description", f"База {name}"),
                    "columns": meta.get("columns", {"code": "code", "description": "description"}),
                    "thresholds": meta.get("thresholds", {"cosine": 0.45, "rerank": 0.6}),
                    "last_updated": meta.get("last_updated", ""),
                    "visible": meta.get("visible", True), # New field
                    "locked": meta.get("locked", False)   # New field
                }
            
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info("💾 Конфигурация успешно сохранена")
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения конфигурации: {e}")

    def _get_embedding_sync(self, text: str) -> np.ndarray:
        """Синхронное получение эмбеддинга через локальную модель"""
        try:
            # Приводим текст к нижнему регистру
            normalized_text = text.lower().strip()
            
            # Токенизация
            inputs = self.tokenizer(
                [normalized_text],
                max_length=1024,
                padding=True,
                truncation=True,
                return_tensors="pt",
            ).to(self.device)

            # Получение эмбеддингов
            with torch.no_grad():
                outputs = self.embedding_model(**inputs)

            # Last token pooling
            last_hidden_state = outputs.last_hidden_state
            attention_mask = inputs["attention_mask"]

            left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
            if left_padding:
                embeddings = last_hidden_state[:, -1]
            else:
                sequence_lengths = attention_mask.sum(dim=1) - 1
                batch_size = last_hidden_state.shape[0]
                embeddings = last_hidden_state[
                    torch.arange(batch_size, device=last_hidden_state.device),
                    sequence_lengths,
                ]

            # Нормализация
            embeddings = torch.nn.functional.normalize(embeddings, p=2, dim=1)
            
            # Конвертация в numpy
            return embeddings.cpu().numpy()[0].astype(np.float32)
        except Exception as e:
            logger.error(f"Ошибка генерации эмбеддинга: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга: {str(e)}")

    async def get_embedding_cached(self, text: str) -> np.ndarray:
        """Получает эмбеддинг с кэшированием (асинхронно)"""
        # Проверяем кэш
        cached_emb = await self.embedding_cache.get(text)
        if cached_emb is not None:
            return cached_emb

        # Если нет в кэше, генерируем
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            self.executor, self._get_embedding_sync, text
        )

        # Сохраняем в кэш
        await self.embedding_cache.set(text, embedding)
        return embedding

    # === МЕТОДЫ СОВМЕСТИМОСТИ (ADAPTERS) ===
    
    def get_thresholds(self):
        """Возвращает пороги для текущей коллекции"""
        meta = self.get_current_database_info()
        thresholds = meta.get("thresholds", {"cosine": 0.45, "rerank": 0.6})
        return thresholds["cosine"], thresholds["rerank"]

    def get_columns(self):
        """Возвращает маппинг колонок для текущей коллекции"""
        meta = self.get_current_database_info()
        return meta.get("columns", {"code": "code", "description": "description"})

    def set_active_collection(self, name: str):
        """Алиас для switch_database с валидацией"""
        if not self.switch_database(name):
             raise ValueError(f"База '{name}' не найдена")

    async def search_similar(
        self,
        collection_name,
        query_embedding,
        top_k,
        score_threshold,
        filter_path: Optional[str] = None,
        filter_level: Optional[int] = None,
        filter_paths: Optional[List[dict]] = None
    ):
        """
        Адаптер для поиска с фильтрацией по score и иерархии.
        Возвращает список словарей, совместимый с MatchResponse.
        
        ОПТИМИЗАЦИЯ: Фильтрация по score_threshold перенесена в search_vectors (на сторону Qdrant).
        Это уменьшает объем передаваемых данных и ускоряет обработку.
        
        Args:
            collection_name: Имя коллекции.
            query_embedding: Вектор запроса.
            top_k: Количество результатов.
            score_threshold: Порог косинусного сходства.
            filter_path: Путь категории для фильтрации (опционально, одиночный).
            filter_level: Уровень иерархии для фильтрации (опционально).
            filter_paths: Список путей для множественной фильтрации (OR логика).
        """
        results = await self.search_vectors(
            query_embedding=query_embedding,
            top_k=top_k,
            collection_name=collection_name,
            score_threshold=score_threshold,
            filter_path=filter_path,
            filter_level=filter_level,
            filter_paths=filter_paths
        )
        
        # Фильтрация по порогу косинусного сходства теперь выполняется в Qdrant
        # filtered_results = [r for r in results if r['score'] >= score_threshold]
        
        return results
        
    def delete_by_code(self, code: str, collection_name: Optional[str] = None) -> bool:
        """Алиас для delete_record"""
        return self.delete_record(code, collection_name)
    
    def clear_cache(self):
        """Очистка кэша эмбеддингов"""
        self.embedding_cache.clear()

    # === СТАНДАРТНЫЕ МЕТОДЫ QDRANT ===

    def load_configuration(self):
        """
        Загрузка/перезагрузка конфигурации векторных баз из JSON файла

        Может вызываться повторно для обновления списка баз без перезапуска сервера

        Конфигурация содержит:
        - Названия коллекций
        - Описания баз
        - Пороговые значения (cosine, rerank)
        - Маппинг колонок метаданных
        """
        if not os.path.exists(self.config_path):
            logger.warning(f"⚠️ Конфигурационный файл не найден: {self.config_path}")
            self._create_default_config(self.config_path)
            return

        try:
            logger.info(f"📂 Загрузка конфигурации из: {self.config_path}")

            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Проверяем существование коллекций в Qdrant
            existing_collections = [
                c.name for c in self.client.get_collections().collections
            ]

            # Запоминаем старое состояние для логирования изменений
            old_collections = set(self.collections_metadata.keys())

            # Очищаем старые метаданные перед обновлением
            self.collections_metadata = {}

            for collection_name, db_config in config.items():
                if collection_name in existing_collections:
                    # Получаем информацию о коллекции из Qdrant
                    collection_info = self.client.get_collection(collection_name)

                    # Сохраняем метаданные коллекции
                    self.collections_metadata[collection_name] = {
                        "name": collection_name,
                        "description": db_config.get(
                            "description", f"База {collection_name}"
                        ),
                        "columns": db_config.get(
                            "columns", {"code": "code", "description": "description"}
                        ),
                        "thresholds": db_config.get(
                            "thresholds", {"cosine": 0.45, "rerank": 0.6}
                        ),
                        "record_count": collection_info.points_count,
                        "dimension": collection_info.config.params.vectors.size,
                        # ИЗМЕНЕНО: Читаем дату из конфига, если её нет - пустая строка
                        "last_updated": db_config.get("last_updated", ""),
                        "visible": db_config.get("visible", True),
                        "locked": db_config.get("locked", False),
                    }

                    logger.info(
                        f"✅ Коллекция '{collection_name}' найдена: "
                        f"{collection_info.points_count} записей, "
                        f"размерность {collection_info.config.params.vectors.size}"
                    )
                else:
                    logger.warning(
                        f"⚠️ Коллекция '{collection_name}' указана в конфиге, "
                        f"но не найдена в Qdrant"
                    )

            # Проверка текущей активной коллекции
            if (
                hasattr(self, "current_collection")
                and self.current_collection not in self.collections_metadata
            ):
                if self.collections_metadata:
                    # Устанавливаем первую найденную коллекцию как активную
                    self.current_collection = next(iter(self.collections_metadata))
                    logger.warning(
                        f"⚠️ Предыдущая активная коллекция '{self.current_collection}' недоступна, "
                        f"переключено на: {self.current_collection}"
                    )
                else:
                    self.current_collection = None
                    logger.error("❌ Не найдено ни одной коллекции в Qdrant")

            # Логируем изменения при перезагрузке
            new_collections = set(self.collections_metadata.keys())
            added = new_collections - old_collections
            removed = old_collections - new_collections

            if added:
                logger.info(f"➕ Добавлены коллекции: {', '.join(added)}")
            if removed:
                logger.info(f"➖ Удалены коллекции: {', '.join(removed)}")

            logger.info(
                f"✅ Конфигурация загружена: {len(self.collections_metadata)} коллекций доступно"
            )

        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON конфига: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка при загрузке конфигурации: {str(e)}")
            raise

    def _cleanup_pending_deletions(self):
        """
        Очистка папок коллекций, помеченных на удаление.
        
        Вызывается при старте сервера ДО подключения к Qdrant,
        когда файлы storage.sqlite ещё не заблокированы.
        """
        import shutil
        
        if not self.pending_deletions_path.exists():
            return
            
        try:
            with open(self.pending_deletions_path, "r", encoding="utf-8") as f:
                pending = json.load(f)
            
            deleted_count = 0
            failed = []
            
            for collection_name in pending.get("collections", []):
                collection_dir = QDRANT_STORAGE_PATH / "collection" / collection_name
                
                if collection_dir.exists():
                    try:
                        shutil.rmtree(collection_dir)
                        logger.info(f"🗑️ Очищена папка отложенного удаления: {collection_name}")
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"⚠️ Не удалось удалить папку {collection_name}: {e}")
                        failed.append(collection_name)
                else:
                    logger.info(f"📁 Папка {collection_name} уже не существует")
            
            # Обновляем файл отложенных удалений
            if failed:
                # Оставляем только те, что не удалось удалить
                with open(self.pending_deletions_path, "w", encoding="utf-8") as f:
                    json.dump({"collections": failed}, f)
            else:
                # Удаляем файл если всё очистили
                self.pending_deletions_path.unlink()
                
            if deleted_count > 0:
                logger.info(f"✅ Очищено {deleted_count} папок отложенных удалений")
                
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при очистке отложенных удалений: {e}")

    def _schedule_deletion(self, collection_name: str):
        """
        Помечает папку коллекции для отложенного удаления.
        
        Папка будет удалена при следующем запуске сервера,
        когда файлы не заблокированы Qdrant.
        
        Args:
            collection_name: Имя коллекции для удаления
        """
        try:
            pending = {"collections": []}
            
            if self.pending_deletions_path.exists():
                with open(self.pending_deletions_path, "r", encoding="utf-8") as f:
                    pending = json.load(f)
            
            if collection_name not in pending["collections"]:
                pending["collections"].append(collection_name)
                
            with open(self.pending_deletions_path, "w", encoding="utf-8") as f:
                json.dump(pending, f, indent=2)
                
            logger.info(f"📋 Коллекция '{collection_name}' помечена для удаления при перезапуске")
            
        except Exception as e:
            logger.warning(f"⚠️ Не удалось записать отложенное удаление: {e}")

    def _create_default_config(self, config_path: str):
        """
        Создание конфигурации по умолчанию если файл не найден

        Args:
            config_path: Путь для сохранения конфига
        """
        logger.info("📝 Создание конфигурации по умолчанию...")

        # Получаем список существующих коллекций в Qdrant
        existing_collections = [
            c.name for c in self.client.get_collections().collections
        ]

        default_config = {}
        for collection_name in existing_collections:
            collection_info = self.client.get_collection(collection_name)

            default_config[collection_name] = {
                "description": f"Векторная база {collection_name}",
                "columns": {"code": "code", "description": "description"},
                "thresholds": {"cosine": 0.45, "rerank": 0.6},
            }

            # Сохраняем метаданные
            self.collections_metadata[collection_name] = {
                "name": collection_name,
                "description": f"Векторная база {collection_name}",
                "columns": {"code": "code", "description": "description"},
                "thresholds": {"cosine": 0.45, "rerank": 0.6},
                "record_count": collection_info.points_count,
                "dimension": collection_info.config.params.vectors.size,
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        # Сохраняем конфиг
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Создана конфигурация для {len(default_config)} коллекций")

    def get_available_databases(self) -> List[Dict]:
        """
        Получение списка доступных баз данных с метаданными

        Returns:
            List[Dict]: Список баз с метаданными
        """
        return [
            {
                "name": name,
                "description": meta["description"],
                "record_count": meta["record_count"],
                "dimension": meta["dimension"],
                "is_active": name == self.current_collection,
            }
            for name, meta in self.collections_metadata.items()
        ]

    def switch_database(self, database_name: str) -> bool:
        """
        Переключение на другую базу данных

        Args:
            database_name: Название коллекции для переключения

        Returns:
            bool: True если успешно переключено
        """
        if database_name not in self.collections_metadata:
            logger.error(f"❌ База '{database_name}' не найдена")
            return False

        old_db = self.current_collection
        self.current_collection = database_name

        logger.info(f"🔄 Переключение базы: {old_db} → {database_name}")
        return True

    def get_current_database_info(self) -> Dict:
        """
        Получение информации о текущей активной базе

        Returns:
            Dict: Метаданные текущей базы
        """
        if not self.current_collection:
            return {}

        return self.collections_metadata.get(self.current_collection, {})

    async def search_vectors(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        collection_name: Optional[str] = None,
        score_threshold: Optional[float] = None,
        filter_path: Optional[str] = None,
        filter_level: Optional[int] = None,
        filter_paths: Optional[List[dict]] = None,
    ) -> List[Dict]:
        """
        Выполнение поиска ближайших соседей (ANN) в Qdrant.

        Этот метод выполняется асинхронно, делегируя блокирующий вызов клиента Qdrant
        в пул потоков (`executor`), чтобы не блокировать Event Loop FastAPI.

        Args:
            query_embedding (List[float]): Вектор запроса.
            top_k (int): Максимальное количество кандидатов.
            collection_name (Optional[str]): Имя коллекции (если None, используется активная).
            score_threshold (Optional[float]): Порог косинусного сходства для фильтрации на стороне БД.
            filter_path (Optional[str]): Путь категории для фильтрации по иерархии (одиночный).
            filter_level (Optional[int]): Уровень иерархии (1, 2, 3...) для фильтрации.
            filter_paths (Optional[List[dict]]): Множественный фильтр: [{"path": "...", "level": N}, ...]
                                                 Используется OR-логика (should).

        Returns:
            List[Dict]: Список найденных записей с метаданными и оценкой сходства (score).
        
        Raises:
            ValueError: Если коллекция не найдена или не выбрана.
        """
        collection = collection_name or self.current_collection

        if not collection:
            raise ValueError("Не указана коллекция для поиска")

        if collection not in self.collections_metadata:
            raise ValueError(f"Коллекция '{collection}' не найдена")

        # Асинхронный поиск через ThreadPoolExecutor
        loop = asyncio.get_event_loop()

        # Если пришел numpy array, конвертируем в список
        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        # Построение фильтра для иерархической фильтрации
        qdrant_filter = None
        
        # Приоритет: множественный фильтр (filter_paths) > одиночный (filter_path)
        if filter_paths and len(filter_paths) > 0:
            # Множественный фильтр с OR-логикой (should)
            # Формат: [{"path": "Арматура → Краны", "level": 2}, ...]
            conditions = []
            for fp in filter_paths:
                path = fp.get("path")
                level = fp.get("level")
                if path and level:
                    conditions.append(
                        FieldCondition(
                            key=f"path_level_{level}",
                            match=MatchValue(value=path)
                        )
                    )
            
            if conditions:
                # should = OR логика (хотя бы одно условие должно выполняться)
                qdrant_filter = Filter(should=conditions)
                paths_str = ", ".join([f"level{fp.get('level')}='{fp.get('path')}'" for fp in filter_paths])
                logger.info(f"🔍 Множественный фильтр иерархии (OR): {paths_str}")
        
        elif filter_path and filter_level:
            # Одиночный фильтр (обратная совместимость)
            # Фильтруем по полю path_level_N, где N = filter_level
            qdrant_filter = Filter(
                must=[
                    FieldCondition(
                        key=f"path_level_{filter_level}",
                        match=MatchValue(value=filter_path)
                    )
                ]
            )
            logger.info(f"🔍 Фильтр иерархии: path_level_{filter_level} = '{filter_path}'")

        def _search():
            # ИСПРАВЛЕНО: search заменен на query_points в новых версиях qdrant-client
            # ОПТИМИЗАЦИЯ: score_threshold передается в запрос для фильтрации на стороне Qdrant
            response = self.client.query_points(
                collection_name=collection,
                query=query_embedding,
                limit=top_k,
                with_payload=True,
                score_threshold=score_threshold,
                query_filter=qdrant_filter,  # Фильтр по иерархии
            )
            return response.points

        search_results = await loop.run_in_executor(self.executor, _search)

        # Получаем маппинг колонок для этой коллекции
        columns = self.collections_metadata[collection]["columns"]

        # Форматирование результатов
        results = []
        for hit in search_results:
            results.append(
                {
                    "id": hit.id,
                    "score": hit.score,
                    "code": hit.payload.get(columns["code"], ""),
                    "description": hit.payload.get(columns["description"], ""),
                    "metadata": hit.payload,
                }
            )

        return results

    def get_record_by_code(
        self, code: str, collection_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Получение записи по коду КСР

        Args:
            code: Код КСР для поиска
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Optional[Dict]: Найденная запись или None
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return None

        columns = self.collections_metadata[collection]["columns"]
        code_field = columns["code"]

        # Поиск по фильтру
        search_result = self.client.scroll(
            collection_name=collection,
            scroll_filter=Filter(
                must=[FieldCondition(key=code_field, match=MatchValue(value=code))]
            ),
            limit=1,
        )

        if search_result[0]:
            point = search_result[0][0]
            return {
                "id": point.id,
                "code": point.payload.get(code_field, ""),
                "description": point.payload.get(columns["description"], ""),
                "metadata": point.payload,
            }

        return None

    def get_all_records(self, collection_name: Optional[str] = None) -> Dict[str, str]:
        """
        Получение всех записей из коллекции

        Args:
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Dict[str, str]: Словарь {код: описание}
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return {}

        columns = self.collections_metadata[collection]["columns"]
        code_field = columns["code"]
        desc_field = columns["description"]

        all_records = {}
        offset = None

        while True:
            # Получаем батч записей
            records, next_offset = self.client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
            )

            # Добавляем в словарь
            for point in records:
                code = point.payload.get(code_field, "")
                description = point.payload.get(desc_field, "")
                if code:
                    all_records[code] = description

            # Проверка завершения
            if next_offset is None:
                break

            offset = next_offset

        return all_records

    def update_record(
        self,
        code: str,
        description: str,
        embedding: List[float],
        collection_name: Optional[str] = None,
        point_id: Optional[str] = None,
        new_metadata: Optional[Dict] = None,
    ) -> bool:
        """
        Обновление или создание записи

        Args:
            code: Код КСР
            description: Описание
            embedding: Вектор эмбеддинга
            collection_name: Название коллекции (если None - текущая)
            point_id: ID записи (опционально)
            new_metadata: Полные метаданные (опционально)

        Returns:
            bool: True если успешно
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return False

        columns = self.collections_metadata[collection]["columns"]

        # Если метаданные не переданы, формируем базовые
        is_new_record = False
        
        if new_metadata is None:
            # Ищем существующую запись для проверки
            existing = self.get_record_by_code(code, collection)
            is_new_record = existing is None
            
            # Генерируем поля path_level_N для иерархической фильтрации
            path_levels = generate_path_levels(description, separator="→")
            
            payload = {
                columns["code"]: code,
                columns["description"]: description,
                **path_levels,  # path_level_1, path_level_2, ..., path_depth
                "timestamp": time.time(),
                "source": "update" if existing else "create",
            }
            # Используем существующий ID или генерируем новый UUID на основе кода
            if point_id is None:
                point_id = existing["id"] if existing else str(uuid.uuid5(uuid.NAMESPACE_DNS, code))
        else:
            payload = new_metadata
            if point_id is None:
                 existing = self.get_record_by_code(code, collection)
                 is_new_record = existing is None
                 point_id = existing["id"] if existing else str(uuid.uuid5(uuid.NAMESPACE_DNS, code))

        # Upsert точки
        self.client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

        # Обновляем счетчик в метаданных, если это новая запись
        if is_new_record:
            self.collections_metadata[collection]["record_count"] += 1

        return True

    def update_records_batch(
        self,
        records: List[Dict[str, str]], # List of {code, description}
        collection_name: Optional[str] = None
    ) -> int:
        """
        Массовое обновление записей с генерацией векторов
        """
        collection = collection_name or self.current_collection
        if not collection or collection not in self.collections_metadata:
            return 0
            
        if not records:
            return 0
            
        columns = self.collections_metadata[collection]["columns"]
        
        # 1. Подготовка текстов
        texts = [r["description"] for r in records]
        codes = [r["code"] for r in records]
        
        # 2. Генерация векторов (батчевая)
        embeddings = self.get_embeddings_batch(texts, batch_size=8)
        
        # 3. Подготовка точек для Qdrant
        points = []
        timestamp = time.time()
        
        for code, desc, emb in zip(codes, texts, embeddings):
            # Генерируем ID (UUID5 от кода) для детерминизма
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, code))
            
            # Генерируем поля path_level_N для иерархической фильтрации
            path_levels = generate_path_levels(desc, separator="→")
            
            payload = {
                columns["code"]: code,
                columns["description"]: desc,
                **path_levels,  # path_level_1, path_level_2, ..., path_depth
                "timestamp": timestamp,
                "source": "batch_update"
            }
            
            points.append(PointStruct(
                id=point_id,
                vector=emb.tolist(),
                payload=payload
            ))
            
        # 4. Upsert в Qdrant (одним запросом)
        self.client.upsert(
            collection_name=collection,
            points=points
        )
        
        # Обновляем счетчик
        try:
             self.collections_metadata[collection]["record_count"] = self.client.get_collection(collection).points_count
        except:
             pass
        
        return len(points)

    def delete_record(self, code: str, collection_name: Optional[str] = None) -> bool:
        """
        Удаление записи по коду

        Args:
            code: Код КСР для удаления
            collection_name: Название коллекции (если None - текущая)

        Returns:
            bool: True если успешно удалено
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return False

        # Находим запись
        record = self.get_record_by_code(code, collection)

        if not record:
            logger.warning(f"⚠️ Запись с кодом '{code}' не найдена")
            return False

        # Удаляем по ID
        self.client.delete(
            collection_name=collection,
            points_selector=[record["id"]],
        )
        
        # Обновляем счетчик в метаданных
        self.collections_metadata[collection]["record_count"] -= 1

        logger.info(f"🗑️ Удалена запись: {code}")
        return True

    def delete_batch_by_codes(self, codes: List[str], collection_name: Optional[str] = None) -> int:
        """
        Пакетное удаление записей по списку кодов
        """
        collection = collection_name or self.current_collection
        if not collection or collection not in self.collections_metadata:
            return 0
            
        if not codes:
            return 0
            
        columns = self.collections_metadata[collection]["columns"]
        code_field = columns["code"]
        
        # Удаляем через фильтр MatchAny
        self.client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key=code_field,
                        match=MatchAny(any=codes)
                    )
                ]
            )
        )
        
        # Обновляем счетчик
        try:
             self.collections_metadata[collection]["record_count"] = self.client.get_collection(collection).points_count
        except:
             pass
             
        return len(codes)

    def get_collection_stats(self, collection_name: Optional[str] = None) -> Dict:
        """
        Получение статистики коллекции

        Args:
            collection_name: Название коллекции (если None - текущая)

        Returns:
            Dict: Статистика коллекции
        """
        collection = collection_name or self.current_collection

        if not collection or collection not in self.collections_metadata:
            return {}

        collection_info = self.client.get_collection(collection)

        return {
            "name": collection,
            "points_count": collection_info.points_count,
            "dimension": collection_info.config.params.vectors.size,
            "distance": collection_info.config.params.vectors.distance.name,
            "status": collection_info.status.name,
        }




# === ИНИЦИАЛИЗАЦИЯ СИСТЕМЫ ===
logger.info("⚙️ Инициализация системы поиска с Qdrant...")

# Инициализация менеджера векторных баз
db_manager = QdrantVectorDatabaseManager(storage_path=QDRANT_STORAGE_PATH)


# Загрузка reranker модели
logger.info(f"🧠 Загрузка reranker на устройстве: {db_manager.device}")
reranker = CrossEncoder(
    RERANKER_PATH,
    device=db_manager.device,
    model_kwargs={
        "torch_dtype": torch.float16 if db_manager.device == "cuda" else torch.float32
    },
)
logger.info("✅ Reranker загружен")


# === FASTAPI ПРИЛОЖЕНИЕ ===
app = FastAPI(
    title="KSR Matcher API с Qdrant",
    description="Высокопроизводительная система поиска с векторной базой Qdrant",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение статических файлов (CSS, JS, изображения)
STATIC_DIR = os.path.join(WEB_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    logger.info(f"✅ Статические файлы подключены из: {STATIC_DIR}")
else:
    logger.warning(f"⚠️ Папка static не найдена: {STATIC_DIR}")


# === PYDANTIC МОДЕЛИ ===
class MatchRequest(BaseModel):
    """
    Запрос на поиск похожих записей.
    
    Attributes:
        text: Текст запроса для поиска.
        database: Имя коллекции (если None - используется активная).
        filter_path: Путь категории для фильтрации (например, "Арматура → Краны").
        filter_level: Уровень иерархии для фильтрации (1, 2, 3...).
        filter_paths: Список путей для множественной фильтрации (OR логика).
                      Формат: [{"path": "...", "level": N}, ...]
    """

    text: str
    database: Optional[str] = None
    filter_path: Optional[str] = None  # Путь для фильтрации по иерархии (одиночный)
    filter_level: Optional[int] = None  # Уровень иерархии (1, 2, 3...)
    filter_paths: Optional[List[dict]] = None  # Множественный фильтр: [{"path": "...", "level": N}, ...]


class Job(BaseModel):
    """Модель фоновой задачи"""
    id: str
    type: str
    status: str  # pending, processing, completed, error
    progress: int = 0
    total: int = 0
    details: str = ""
    created_at: float
    error: Optional[str] = None


class ColumnMapping(BaseModel):
    """Маппинг колонок для импорта"""
    code_column: str
    desc_columns: List[str]
    separator: str = " "


class UpdatePointRequest(BaseModel):
    """Запрос на обновление одной ячейки"""
    code: str
    field: str # 'description' or 'code'
    value: str


class CollectionConfig(BaseModel):
    """
    Конфигурация коллекции для обновления через API.
    
    ВАЖНО: Поле 'locked' НЕ может быть изменено через API!
    Защита коллекции устанавливается только через прямое редактирование
    файла vector_databases.json или через код сервера.
    """
    visible: bool = True
    thresholds: Dict[str, float]
    # locked намеренно исключён из API - защита только через код!


class CandidateResult(BaseModel):
    """Результат поиска - один кандидат"""

    rank: int
    code: str
    description: str
    reranker_score: float
    cosine_similarity: float


class DatabaseInfo(BaseModel):
    """Информация о векторной базе/коллекции"""

    name: str
    description: str
    record_count: int
    is_active: bool
    thresholds: dict


class MatchResponse(BaseModel):
    """Ответ на запрос поиска"""

    query: str
    database: str
    candidates: List[CandidateResult]
    processing_time: float
    status: str


class DatabasesResponse(BaseModel):
    """Список доступных баз данных"""

    databases: List[DatabaseInfo]
    current_database: str


class UpdateRequest(BaseModel):
    """Запрос на обновление записи"""

    code: str
    description: str
    database: Optional[str] = None


class BatchUpdateRequest(BaseModel):
    """Запрос на пакетное обновление записей"""
    records: List[UpdateRequest]
    database: Optional[str] = None


class BatchDeleteRequest(BaseModel):
    """Запрос на пакетное удаление записей"""
    codes: List[str]
    database: Optional[str] = None


class CopyEvent(BaseModel):
    """События копирования кода (для аналитики)"""

    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: Optional[float] = None
    cosine_similarity: Optional[float] = None


class DislikeEvent(BaseModel):
    """События дизлайка результата (для аналитики)"""

    timestamp: str
    query: str
    selected_code: str
    position: int
    description: str
    database: str
    reranker_score: Optional[float] = None
    cosine_similarity: Optional[float] = None
    action: str = "dislike"


# === МЕНЕДЖЕР ФОНОВЫХ ЗАДАЧ ===
class BackgroundJobManager:
    """
    Менеджер фоновых задач для импорта данных и других долгих операций.
    Использует asyncio.Queue для очереди и хранит статус задач в памяти.
    """
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.queue = asyncio.Queue()
        self.is_running = False

    async def submit_job(self, job_type: str, data: dict) -> str:
        """Создает задачу и добавляет в очередь"""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            type=job_type,
            status="pending",
            created_at=time.time(),
            details=f"Job {job_type} queued"
        )
        self.jobs[job_id] = job
        await self.queue.put((job_id, data))
        
        if not self.is_running:
            asyncio.create_task(self.worker())
            
        return job_id

    async def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    async def list_jobs(self) -> List[Job]:
        # Сортировка: сначала новые
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def worker(self):
        """Фоновый воркер для обработки очереди"""
        self.is_running = True
        logger.info("👷 Background worker started")
        
        while True:
            try:
                job_id, data = await self.queue.get()
                job = self.jobs[job_id]
                
                logger.info(f"👷 Starting job {job_id} ({job.type})")
                job.status = "processing"
                job.progress = 0
                
                try:
                    if job.type == "import_batch":
                        await self.process_import(job, data)
                    else:
                        logger.warning(f"Unknown job type: {job.type}")
                        job.status = "error"
                        job.error = f"Unknown job type: {job.type}"
                
                except Exception as e:
                    logger.error(f"❌ Job {job_id} failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    job.status = "error"
                    job.error = str(e)
                else:
                    if job.status != "error":
                        job.status = "completed"
                        job.progress = 100
                        logger.info(f"✅ Job {job_id} completed")
                
                finally:
                    self.queue.task_done()
                    
            except Exception as e:
                logger.error(f"Worker crashed: {e}")
                await asyncio.sleep(1)

    async def process_import(self, job: Job, data: dict):
        """
        Логика импорта данных.
        data: {
            "collection_name": str,
            "records": List[dict], # [{"code": "...", "description": "..."}]
            "recreate": bool
        }
        """
        collection_name = data["collection_name"]
        records = data["records"]
        total = len(records)
        job.total = total
        
        # Получаем доступ к глобальному db_manager
        global db_manager
        
        # Проверяем существование коллекции
        if collection_name not in db_manager.collections_metadata:
            raise ValueError(f"Коллекция '{collection_name}' не найдена. Сначала создайте её.")
        
        # КРИТИЧНО: Проверяем размерность коллекции vs модели
        collection_dim = db_manager.collections_metadata[collection_name].get("dimension")
        model_dim = db_manager.embedding_model.config.hidden_size
        
        if collection_dim and collection_dim != model_dim:
            raise ValueError(
                f"Размерность коллекции ({collection_dim}) не совпадает с размерностью модели ({model_dim}). "
                f"Удалите коллекцию '{collection_name}' и создайте заново."
            )
             
        BATCH_SIZE = 32
        processed = 0
        
        # Итерируемся батчами
        for i in range(0, total, BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            
            # Подготовка данных
            texts = [r["description"] for r in batch]
            codes = [r["code"] for r in batch]
            metas = [r.get("meta", {}) for r in batch]
            
            # === CRITICAL: GPU LOCK ===
            # Защищаем вызов тяжелой модели
            async with db_manager.gpu_lock:
                 embeddings = await asyncio.get_event_loop().run_in_executor(
                     db_manager.executor,
                     lambda: db_manager.get_embeddings_batch(texts, batch_size=BATCH_SIZE)
                 )
            
            # Формирование точек
            points = []
            timestamp = time.time()
            columns = db_manager.collections_metadata.get(collection_name, {}).get("columns", {"code": "code", "description": "description"})
            
            for code, desc, emb, meta in zip(codes, texts, embeddings, metas):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(code)))
                
                # Генерируем поля path_level_N для иерархической фильтрации
                # Это позволяет быстро фильтровать по категориям в Qdrant
                path_levels = generate_path_levels(desc, separator="→")
                
                payload = {
                    columns["code"]: code,
                    columns["description"]: desc,
                    **path_levels,  # path_level_1, path_level_2, ..., path_depth
                    "timestamp": timestamp,
                    "source": "import_job",
                    **meta
                }
                
                points.append(PointStruct(
                    id=point_id,
                    vector=emb.tolist(),
                    payload=payload
                ))
            
            # Запись в Qdrant (не требует GPU lock)
            db_manager.client.upsert(
                collection_name=collection_name,
                points=points
            )
            
            processed += len(batch)
            job.progress = int((processed / total) * 100)
            
            # Обновляем счетчик
            if collection_name in db_manager.collections_metadata:
                 db_manager.collections_metadata[collection_name]["record_count"] = processed # Примерно, точнее будет после всего
            
            # Даем передышку event loop
            await asyncio.sleep(0.01)
            
        # Финальное обновление счетчика и даты
        info = db_manager.client.get_collection(collection_name)
        if collection_name in db_manager.collections_metadata:
            db_manager.collections_metadata[collection_name]["record_count"] = info.points_count
            db_manager.collections_metadata[collection_name]["last_updated"] = datetime.now().strftime("%d.%m.%Y")
            db_manager.save_configuration()

# Инициализация менеджера задач (после определения классов)
job_manager = BackgroundJobManager()

# Инициализация сервиса иерархии (кэш на 5 минут)
hierarchy_service = HierarchyService(cache_ttl=300)

# === MIDDLEWARE ===
@app.middleware("http")
async def log_processing_time(request, call_next):
    """Логирование времени обработки каждого запроса"""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(f"{request.method} {request.url.path} - {process_time:.3f}s")
    return response


# === ОСНОВНЫЕ ENDPOINTS ===
@app.get("/", response_class=HTMLResponse)
async def root():
    """Возвращает веб-интерфейс приложения"""
    try:
        index_path = os.path.join(WEB_DIR, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"Интерфейс не найден: {index_path}"
        )


@app.get("/databases")
async def get_databases():
    """
    Получение списка доступных баз данных для фронтенда.
    
    ВАЖНО: Возвращает только коллекции с visible=True.
    Скрытые коллекции не отображаются в основном интерфейсе поиска.

    Returns:
        {
            "databases": [
                {
                    "name": "ksr_main",
                    "description": "ksr_main",
                    "record_count": 121905,
                    "dimension": 1024,
                    "thresholds": {"cosine": 0.45, "rerank": 0.6}
                }
            ],
            "current_database": "ksr_main"
        }
    """
    try:
        databases_list = []

        # Фильтруем по visible=True (скрытые коллекции не показываем в UI поиска)
        for name, meta in db_manager.collections_metadata.items():
            # Пропускаем скрытые коллекции
            if not meta.get("visible", True):
                continue
                
            databases_list.append(
                {
                    "name": name,
                    "description": meta.get("description", name),
                    "record_count": meta.get("record_count", 0),
                    "dimension": meta.get("dimension", 1024),
                    "thresholds": meta.get(
                        "thresholds", {"cosine": 0.45, "rerank": 0.6}
                    ),
                    "last_updated": meta.get("last_updated", ""),
                }
            )

        return {
            "databases": databases_list,
            "current_database": db_manager.current_collection,
        }

    except Exception as e:
        logger.error(f"❌ Ошибка получения списка баз: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка получения баз данных: {str(e)}"
        )


@app.post("/set_database")
async def set_database(database_name: str):
    """Устанавливает активную векторную коллекцию"""
    try:
        db_manager.set_active_collection(database_name)
        return {
            "status": "success",
            "message": f"Активная коллекция установлена: {database_name}",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/clear_cache")
async def clear_cache():
    """Очищает кэш эмбеддингов запросов"""
    db_manager.clear_cache()
    return {"status": "success", "message": "Кэш эмбеддингов очищен"}


@app.post("/match", response_model=MatchResponse)
async def match_ksr(request: MatchRequest):
    """
    Основной эндпоинт поиска (Stage 1 Retrieval + Stage 2 Reranking).

    Алгоритм работы:
    1.  **Проверка**: Валидация входного текста и выбор коллекции.
    2.  **Embedding**: Генерация вектора для текста запроса (с кэшированием).
    3.  **Retrieval**: Поиск топ-1500 кандидатов в Qdrant по косинусному сходству.
    4.  **Reranking**:
        *   Отбираются топ-200 кандидатов.
        *   Cross-Encoder (BGE-M3) оценивает релевантность каждой пары (запрос, кандидат).
        *   Фильтрация по порогу (`rerank_threshold`).
    5.  **Fallback**: Если после фильтрации пусто, возвращаются лучшие кандидаты по скору (даже низкому), чтобы не отдавать пустой список.
    6.  **Ответ**: Возврат списка отсортированных кандидатов и метрик времени.

    Args:
        request (MatchRequest): JSON с текстом запроса и именем базы.

    Returns:
        MatchResponse: Структурированный ответ с кандидатами.
    """
    start_time = time.time()
    query_text = request.text.strip()

    if not query_text:
        raise HTTPException(status_code=400, detail="Текст не может быть пустым")

    # Выбор коллекции для поиска
    original_collection = None
    if request.database:
        original_collection = db_manager.current_collection
        try:
            db_manager.set_active_collection(request.database)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    try:
        collection_name = db_manager.current_collection

        # Получение порогов из конфигурации
        COSINE_THRESHOLD, RERANK_THRESHOLD = db_manager.get_thresholds()

        # Получение маппинга колонок
        columns = db_manager.get_columns()

        # Параметры поиска
        TOP_K_QDRANT = 500
        MAX_FOR_RERANK = 100
        MAX_RESULTS = 100

        # === ШАГ 1: Генерация эмбеддинга запроса (асинхронно с кэшем) ===
        query_emb = await db_manager.get_embedding_cached(query_text)

        # === ШАГ 2: Поиск в Qdrant (теперь асинхронно!) ===
        # Если указан фильтр по иерархии - применяем его
        # Приоритет: filter_paths (множественный) > filter_path (одиночный)
        candidates = await db_manager.search_similar(
            collection_name=collection_name,
            query_embedding=query_emb,
            top_k=TOP_K_QDRANT,
            score_threshold=COSINE_THRESHOLD,
            filter_path=request.filter_path,
            filter_level=request.filter_level,
            filter_paths=request.filter_paths,  # Множественный фильтр категорий
        )

        if not candidates:
            logger.warning(f"⚠️ No candidates found in Qdrant for query: '{query_text}'")
            return MatchResponse(
                query=query_text,
                database=collection_name,
                candidates=[],
                processing_time=time.time() - start_time,
                status="not_found_in_vector_db",
            )

        # === ШАГ 3: Ограничиваем для reranking ===
        candidates_for_rerank = candidates[:MAX_FOR_RERANK]

        # === ШАГ 4: Reranking ===
        normalized_query = query_text.lower().strip()
        candidate_pairs = [
            (normalized_query, c["description"]) for c in candidates_for_rerank
        ]

        loop = asyncio.get_event_loop()
        rerank_scores = await loop.run_in_executor(
            db_manager.executor, lambda: reranker.predict(candidate_pairs)
        )

        # === ШАГ 5: Строгая фильтрация по порогу reranker ===
        # Результаты с rerank_score ниже порога НЕ попадают в выдачу
        valid_results = []
        for idx, (candidate, rerank_score) in enumerate(
            zip(candidates_for_rerank, rerank_scores)
        ):
            if rerank_score >= RERANK_THRESHOLD:
                valid_results.append({**candidate, "rerank_score": float(rerank_score)})

        # Логируем если ничего не прошло порог (но НЕ используем fallback)
        if not valid_results:
            max_rerank = float(np.max(rerank_scores)) if len(rerank_scores) > 0 else 0.0
            logger.warning(
                f"⚠️ Ничего не прошло порог reranker. "
                f"Макс. score: {max_rerank:.4f}, Порог: {RERANK_THRESHOLD}"
            )
            # Возвращаем пустой список - строгая фильтрация

        # === ШАГ 6: Сортировка по reranker score ===
        valid_results.sort(key=lambda x: x["rerank_score"], reverse=True)

        # === ШАГ 7: Формирование финального ответа ===
        final_candidates = [
            CandidateResult(
                rank=idx + 1,
                code=r["code"],
                description=r["description"],
                reranker_score=r["rerank_score"],
                cosine_similarity=r["score"],
            )
            for idx, r in enumerate(valid_results[:MAX_RESULTS])
        ]

        processing_time = time.time() - start_time

        logger.info(
            f"✅ Запрос: '{query_text[:50]}...' | "
            f"Найдено в Qdrant: {len(candidates)} | "
            f"Прошло reranker: {len(valid_results)} | "
            f"Возвращено: {len(final_candidates)} | "
            f"Время: {processing_time:.3f}с"
        )

        return MatchResponse(
            query=query_text,
            database=collection_name,
            candidates=final_candidates,
            processing_time=processing_time,
            status="success",
        )

    finally:
        # Восстановление исходной коллекции
        if original_collection and original_collection != db_manager.current_collection:
            db_manager.set_active_collection(original_collection)

@app.get("/health")
async def health_check():
    """
    Health check endpoint - проверка работоспособности сервера

    Returns:
        Статус сервера и основная информация о системе
    """
    return {
        "status": "ok",
        "device": db_manager.device,
        "current_database": db_manager.current_collection,
        "available_databases": len(db_manager.collections_metadata),
        "databases_list": list(db_manager.collections_metadata.keys()),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# === ENDPOINTS ИЕРАРХИЧЕСКОГО КАТАЛОГА ===
@app.get("/hierarchy/{database_name}")
async def get_hierarchy(database_name: str, max_depth: int = 10):
    """
    Получение дерева иерархии категорий для коллекции.
    
    Строит навигационное дерево из полей path_level_N.
    Результаты кэшируются на 5 минут для производительности.
    
    Args:
        database_name: Имя коллекции в Qdrant.
        max_depth: Максимальная глубина дерева (по умолчанию 10).
    
    Returns:
        {
            "tree": [
                {
                    "name": "Арматура",
                    "path": "Арматура",
                    "level": 1,
                    "count": 500,
                    "children": [
                        {"name": "Краны", "path": "Арматура → Краны", "level": 2, ...}
                    ]
                }
            ],
            "total_categories": 15,
            "total_items": 12000,
            "max_depth": 4,
            "cached": true,
            "cache_age": 120
        }
    
    Raises:
        404: Коллекция не найдена.
        500: Ошибка построения иерархии.
    """
    # Проверяем существование коллекции
    if database_name not in db_manager.collections_metadata:
        raise HTTPException(
            status_code=404,
            detail=f"Коллекция '{database_name}' не найдена"
        )
    
    try:
        # Получаем дерево через сервис (с кэшированием)
        result = await hierarchy_service.get_hierarchy(
            client=db_manager.client,
            collection_name=database_name,
            separator="→",
            max_depth=max_depth
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка построения иерархии для '{database_name}': {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка построения иерархии: {str(e)}"
        )


@app.get("/hierarchy/{database_name}/children")
async def get_hierarchy_children(
    database_name: str, 
    parent_path: str = "",
    level: int = 1
):
    """
    Получение дочерних категорий для ленивой загрузки.
    
    ОПТИМИЗИРОВАНО: Использует прямой запрос к Qdrant без построения полного дерева!
    Загружает только непосредственных потомков указанной категории.
    Результаты кэшируются отдельно для каждого пути (TTL 5 минут).
    
    Args:
        database_name: Имя коллекции в Qdrant.
        parent_path: Путь родительской категории (пустой = корень).
        level: Уровень запрашиваемых детей (1 = верхний уровень, игнорируется при parent_path).
    
    Returns:
        {
            "children": [
                {
                    "name": "Арматура",
                    "path": "Арматура",
                    "level": 1,
                    "count": 500,
                    "has_children": true
                }
            ],
            "parent_path": "",
            "total": 15,
            "cached": true
        }
    """
    if database_name not in db_manager.collections_metadata:
        raise HTTPException(
            status_code=404,
            detail=f"Коллекция '{database_name}' не найдена"
        )
    
    try:
        # Определяем уровень родителя на основе пути
        # Пустой parent_path = корень (level 0), дети будут level 1
        # Если parent_path задан - вычисляем уровень по количеству разделителей
        if parent_path:
            # Подсчитываем уровень по количеству " → " в пути
            separator_count = parent_path.count(" → ")
            parent_level = separator_count + 1  # "A" = level 1, "A → B" = level 2
        else:
            parent_level = 0  # Корень
        
        # Используем оптимизированный прямой метод (без построения полного дерева!)
        result = await hierarchy_service.get_children_direct(
            client=db_manager.client,
            collection_name=database_name,
            parent_path=parent_path,
            parent_level=parent_level,
            separator="→"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения дочерних категорий: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка получения дочерних категорий: {str(e)}"
        )


@app.post("/hierarchy/{database_name}/invalidate")
async def invalidate_hierarchy_cache(database_name: str):
    """
    Инвалидация кэша иерархии для коллекции.
    
    Вызывается после массового обновления данных,
    чтобы дерево перестроилось при следующем запросе.
    
    Args:
        database_name: Имя коллекции.
    
    Returns:
        {"status": "success", "message": "..."}
    """
    hierarchy_service.invalidate_cache(database_name)
    return {
        "status": "success",
        "message": f"Кэш иерархии для '{database_name}' очищен"
    }


class HierarchySearchRequest(BaseModel):
    """
    Запрос на семантический поиск по каталогу категорий.
    
    Attributes:
        text: Текст запроса для поиска категорий.
        top_k: Количество категорий в результате (по умолчанию 10).
    """
    text: str
    top_k: int = 10


@app.post("/hierarchy/{database_name}/search")
async def search_hierarchy_categories(database_name: str, request: HierarchySearchRequest):
    """
    Семантический поиск по каталогу категорий.
    
    Использует векторный поиск для нахождения релевантных категорий.
    Алгоритм:
    1. Выполняет поиск по коллекции через embedding + Qdrant
    2. Группирует результаты по категориям (path_level_N)
    3. Ранжирует категории по среднему score и количеству попаданий
    4. Применяет rerank для финального ранжирования
    5. Возвращает топ-N категорий с путями для навигации
    
    Args:
        database_name: Имя коллекции в Qdrant.
        request: HierarchySearchRequest с текстом запроса.
    
    Returns:
        {
            "categories": [
                {
                    "path": "Арматура → Краны",
                    "level": 2,
                    "name": "Краны",
                    "hits": 15,
                    "avg_score": 0.78,
                    "best_score": 0.92
                }
            ],
            "query": "...",
            "total_found": 10
        }
    """
    # Проверяем существование коллекции
    if database_name not in db_manager.collections_metadata:
        raise HTTPException(
            status_code=404,
            detail=f"Коллекция '{database_name}' не найдена"
        )
    
    query_text = request.text.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Текст запроса не может быть пустым")
    
    try:
        # Получаем пороги из конфигурации коллекции
        meta = db_manager.collections_metadata.get(database_name, {})
        thresholds = meta.get("thresholds", {})
        cosine_threshold = thresholds.get("cosine", 0.3)  # Для категорий - чуть ниже порог
        
        # === ШАГ 1: Генерация эмбеддинга (используем кэшированный метод) ===
        query_embedding = await db_manager.get_embedding_cached(query_text)
        
        # === ШАГ 2: Поиск в Qdrant (больше кандидатов для группировки) ===
        original_collection = db_manager.current_collection
        db_manager.set_active_collection(database_name)
        
        # Используем search_similar - правильный метод для поиска
        candidates = await db_manager.search_similar(
            collection_name=database_name,
            query_embedding=query_embedding,
            top_k=500,  # Много кандидатов для группировки по категориям
            score_threshold=cosine_threshold
        )
        
        # Восстанавливаем коллекцию
        if original_collection:
            db_manager.set_active_collection(original_collection)
        
        if not candidates:
            return {
                "categories": [],
                "query": query_text,
                "total_found": 0
            }
        
        # === ШАГ 3: Группировка по КАТЕГОРИЯМ (исключаем последний уровень - материалы) ===
        # Собираем статистику по всем уровням path_level_N кроме самого глубокого
        # ВАЖНО: search_similar возвращает metadata вместо payload!
        category_stats = {}  # {path: {level, hits, scores, name}}
        
        logger.info(f"📊 Обработка {len(candidates)} кандидатов для группировки по категориям")
        
        for candidate in candidates:
            # metadata содержит все поля из payload Qdrant
            metadata = candidate.get("metadata", {})
            score = candidate.get("score", 0)
            
            # Определяем максимальный уровень для этого кандидата (это материал)
            max_level = 0
            for level in range(1, 11):
                if f"path_level_{level}" in metadata and metadata[f"path_level_{level}"]:
                    max_level = level
            
            # Собираем статистику только по уровням 1...(max_level-1) - это категории
            # Последний уровень (max_level) - это материал, его пропускаем
            for level in range(1, max_level):  # До предпоследнего уровня
                path_key = f"path_level_{level}"
                if path_key in metadata and metadata[path_key]:
                    path = metadata[path_key]
                    
                    if path not in category_stats:
                        # Извлекаем название (последний сегмент пути)
                        name = path.split(" → ")[-1] if " → " in path else path
                        category_stats[path] = {
                            "path": path,
                            "level": level,
                            "name": name,
                            "hits": 0,
                            "scores": []
                        }
                    
                    category_stats[path]["hits"] += 1
                    category_stats[path]["scores"].append(score)
        
        logger.info(f"📊 Найдено {len(category_stats)} уникальных категорий")
        
        # === ШАГ 4: Ранжирование категорий ===
        # Вычисляем метрики для каждой категории
        ranked_categories = []
        for path, stats in category_stats.items():
            scores = stats["scores"]
            avg_score = sum(scores) / len(scores) if scores else 0
            best_score = max(scores) if scores else 0
            
            # Комбинированный score: учитываем и качество, и количество
            # Формула: avg_score * log(1 + hits) - баланс качества и популярности
            import math
            combined_score = avg_score * math.log(1 + stats["hits"])
            
            ranked_categories.append({
                "path": stats["path"],
                "level": stats["level"],
                "name": stats["name"],
                "hits": stats["hits"],
                "avg_score": round(avg_score, 4),
                "best_score": round(best_score, 4),
                "combined_score": round(combined_score, 4)
            })
        
        # Сортируем по комбинированному score
        ranked_categories.sort(key=lambda x: x["combined_score"], reverse=True)
        
        # === ШАГ 5: Rerank топ кандидатов (опционально) ===
        # Для категорий можно применить rerank по названиям
        top_categories = ranked_categories[:request.top_k * 2]  # Берём с запасом
        
        if reranker and len(top_categories) > 0:
            # Формируем пары для rerank
            normalized_query = query_text.lower().strip()
            rerank_pairs = [
                (normalized_query, cat["name"]) for cat in top_categories
            ]
            
            loop = asyncio.get_event_loop()
            rerank_scores = await loop.run_in_executor(
                db_manager.executor, lambda: reranker.predict(rerank_pairs)
            )
            
            # Добавляем rerank score и пересортировываем
            for i, cat in enumerate(top_categories):
                cat["rerank_score"] = round(float(rerank_scores[i]), 4)
            
            # Сортируем по rerank score
            top_categories.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        # Берём финальный топ
        final_categories = top_categories[:request.top_k]
        
        logger.info(
            f"🔍 Поиск категорий: '{query_text[:30]}...' | "
            f"Найдено: {len(final_categories)} категорий из {len(category_stats)}"
        )
        
        return {
            "categories": final_categories,
            "query": query_text,
            "total_found": len(final_categories)
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка поиска категорий: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка поиска категорий: {str(e)}"
        )


@app.get("/stats")
async def get_stats():
    """Детальная статистика производительности"""
    collections_info = []
    for name in db_manager.collections_metadata.keys():
        try:
            info = db_manager.get_collection_stats(name)
            collections_info.append(info)
        except Exception as e:
            logger.error(f"Ошибка получения информации о '{name}': {e}")

    return {
        "cache_entries": len(db_manager.embedding_cache.cache),
        "max_cache_size": db_manager.embedding_cache.max_size,
        "collections": collections_info,
        "device": db_manager.device,
        "executor_workers": db_manager.executor._max_workers,
    }


# === ADMIN ENDPOINTS ===
# Административная панель для управления коллекциями, импорта данных
# и мониторинга фоновых задач. Доступ защищён паролем.

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """
    Возвращает HTML-страницу административной панели.
    
    Панель позволяет:
    - Просматривать и редактировать коллекции
    - Импортировать данные из CSV/Excel
    - Настраивать пороги поиска
    - Мониторить фоновые задачи
    """
    try:
        admin_path = WEB_DIR / "admin.html"
        with open(admin_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(404, "Admin interface not found")


class AuthRequest(BaseModel):
    """Запрос аутентификации для админ-панели"""
    password: str


@app.post("/admin/auth")
async def admin_auth(req: AuthRequest):
    """
    Аутентификация администратора.
    
    Простая проверка пароля без сессий (stateless).
    В продакшн-среде рекомендуется использовать полноценную аутентификацию.
    
    Returns:
        {"status": "ok", "token": "..."} при успехе
        401 Unauthorized при неверном пароле
    """
    # TODO: В продакшне заменить на безопасное хранение пароля
    if req.password == "admin123":
        return {"status": "ok", "token": "admin-token-valid"}
    raise HTTPException(status_code=401, detail="Invalid password")

@app.get("/admin/collections")
async def admin_list_collections():
    """
    Получение списка всех коллекций для админ-панели.
    
    В отличие от /databases, возвращает ВСЕ коллекции,
    включая скрытые (visible=False).
    
    Returns:
        {"collections": [список коллекций с полными метаданными]}
    """
    return {
        "collections": [
            {**meta, "is_active": name == db_manager.current_collection}
            for name, meta in db_manager.collections_metadata.items()
        ]
    }


@app.post("/admin/collections/{name}/config")
async def admin_update_config(name: str, config: CollectionConfig):
    """
    Обновление настроек коллекции (пороги, видимость).
    
    ВАЖНО: Флаг 'locked' НЕ может быть изменён через этот endpoint!
    Защита коллекции устанавливается только через прямое редактирование
    файла vector_databases.json.
    
    Args:
        name: Имя коллекции
        config: Новые настройки (thresholds, visible)
    
    Returns:
        {"status": "success", "config": обновлённые метаданные}
    """
    if name not in db_manager.collections_metadata:
        raise HTTPException(404, "Collection not found")
    
    meta = db_manager.collections_metadata[name]
    meta["thresholds"] = config.thresholds
    meta["visible"] = config.visible
    # ВАЖНО: locked НЕ обновляется через API - только через код/файл!
    
    # Сохраняем немедленно
    db_manager.save_configuration()
    
    return {"status": "success", "config": meta}

@app.delete("/admin/collections/{name}")
async def admin_delete_collection(name: str):
    """
    Полное удаление коллекции из Qdrant.
    
    ВНИМАНИЕ: Операция необратима! Все данные будут удалены.
    
    Защищённые коллекции (locked=True) НЕ могут быть удалены через API.
    Для снятия защиты необходимо вручную изменить файл vector_databases.json.
    
    Args:
        name: Имя коллекции для удаления
    
    Returns:
        {"status": "success"} при успехе
        403 если коллекция защищена (locked)
        404 если коллекция не найдена
    """
    if name not in db_manager.collections_metadata:
        raise HTTPException(404, "Коллекция не найдена")
    
    # Проверяем флаг защиты
    meta = db_manager.collections_metadata[name]
    if meta.get("locked", False):
        logger.warning(f"🔒 Попытка удаления защищённой коллекции: {name}")
        raise HTTPException(
            status_code=403, 
            detail="Невозможно удалить защищённую коллекцию. Снимите защиту через файл конфигурации."
        )
    
    try:
        import shutil
        
        # 1. Удаляем из Qdrant API
        db_manager.client.delete_collection(name)
        logger.info(f"🗑️ Коллекция '{name}' удалена из Qdrant API")
        
        # 2. Удаляем из метаданных приложения
        del db_manager.collections_metadata[name]
        
        # 3. Если была активной - сбрасываем или меняем
        if db_manager.current_collection == name:
            db_manager.current_collection = next(iter(db_manager.collections_metadata)) if db_manager.collections_metadata else None
            
        # 4. Сохраняем конфиг vector_databases.json
        db_manager.save_configuration()
        logger.info(f"💾 Конфигурация обновлена: коллекция '{name}' удалена")
        
        # 5. Принудительно обновляем meta.json Qdrant
        meta_json_path = QDRANT_STORAGE_PATH / "meta.json"
        if meta_json_path.exists():
            try:
                with open(meta_json_path, "r", encoding="utf-8") as f:
                    meta_data = json.load(f)
                
                if "collections" in meta_data and name in meta_data["collections"]:
                    del meta_data["collections"][name]
                    
                    with open(meta_json_path, "w", encoding="utf-8") as f:
                        json.dump(meta_data, f, indent=4, ensure_ascii=False)
                    
                    logger.info(f"🗑️ Коллекция '{name}' удалена из meta.json")
            except Exception as meta_err:
                logger.warning(f"⚠️ Не удалось обновить meta.json: {meta_err}")
        
        # 6. ПОЛНОЕ УДАЛЕНИЕ: пытаемся удалить папку с данными коллекции
        collection_dir = QDRANT_STORAGE_PATH / "collection" / name
        folder_deleted = False
        
        if collection_dir.exists():
            try:
                # Пробуем удалить сразу
                shutil.rmtree(collection_dir)
                logger.info(f"🗑️ Удалена папка с эмбеддингами: {collection_dir}")
                folder_deleted = True
            except PermissionError:
                # Файлы заблокированы Qdrant - планируем отложенное удаление
                db_manager._schedule_deletion(name)
                logger.warning(
                    f"⚠️ Папка {name} заблокирована. "
                    f"Будет удалена при следующем запуске сервера."
                )
            except Exception as e:
                # Другая ошибка - тоже планируем отложенное удаление
                db_manager._schedule_deletion(name)
                logger.warning(f"⚠️ Ошибка удаления папки {name}: {e}. Запланировано отложенное удаление.")
        
        if folder_deleted:
            logger.info(f"✅ Коллекция '{name}' полностью удалена (включая все данные)")
            return {"status": "success", "message": f"Коллекция '{name}' полностью удалена"}
        else:
            logger.info(f"✅ Коллекция '{name}' удалена. Папка с данными будет очищена при перезапуске сервера.")
            return {
                "status": "success", 
                "message": f"Коллекция '{name}' удалена. Папка с данными будет очищена при перезапуске сервера.",
                "pending_cleanup": True
            }
        
    except HTTPException:
        raise  # Пробрасываем HTTP ошибки как есть
    except Exception as e:
        logger.error(f"❌ Ошибка удаления коллекции {name}: {e}")
        raise HTTPException(500, str(e))

@app.get("/admin/collections/{name}/data")
async def admin_get_data(name: str, limit: int = 50, offset: str = None):
    """
    Пагинированный просмотр записей коллекции.
    
    Использует scroll API Qdrant для эффективной постраничной навигации.
    
    Args:
        name: Имя коллекции
        limit: Количество записей на страницу (default: 50)
        offset: Токен следующей страницы (из предыдущего ответа)
    
    Returns:
        {
            "data": [список записей],
            "next_offset": токен для следующей страницы или null,
            "total": общее количество записей
        }
    """
    if name not in db_manager.collections_metadata:
        raise HTTPException(404, "Collection not found")
        
    try:
        # Используем scroll api
        points, next_offset = db_manager.client.scroll(
            collection_name=name,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        
        columns = db_manager.collections_metadata[name]["columns"]
        
        data = []
        for p in points:
            data.append({
                "id": p.id,
                "code": p.payload.get(columns["code"]),
                "description": p.payload.get(columns["description"]),
                "meta": p.payload
            })
            
        return {
            "data": data,
            "next_offset": next_offset,
            "total": db_manager.collections_metadata[name]["record_count"]
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/admin/collections/{name}/data/{id}")
async def admin_update_point(name: str, id: str, req: UpdatePointRequest):
    """Редактирование конкретной ячейки"""
    if name not in db_manager.collections_metadata:
        raise HTTPException(404, "Collection not found")
        
    columns = db_manager.collections_metadata[name]["columns"]
    
    # Получаем текущую точку
    points = db_manager.client.retrieve(
        collection_name=name,
        ids=[id],
        with_payload=True,
        with_vectors=True 
    )
    
    if not points:
        raise HTTPException(404, "Point not found")
        
    point = points[0]
    payload = point.payload
    vector = point.vector
    
    # Обновляем поле
    if req.field == "description":
        # Если меняется описание, нужно пересчитать вектор и path_levels!
        new_text = req.value
        payload[columns["description"]] = new_text
        
        # Пересчитываем поля path_level_N для иерархической фильтрации
        path_levels = generate_path_levels(new_text, separator="→")
        payload.update(path_levels)
        
        # Защищенный пересчет вектора
        async with db_manager.gpu_lock:
            emb = await db_manager.get_embedding_cached(new_text)
            vector = emb.tolist() if isinstance(emb, np.ndarray) else emb
            
    elif req.field == "code":
        payload[columns["code"]] = req.value
        # Вектор не меняется
        
    else:
        # Произвольное поле меты
        payload[req.field] = req.value
        
    # Сохраняем
    db_manager.client.upsert(
        collection_name=name,
        points=[
            PointStruct(
                id=id,
                vector=vector,
                payload=payload
            )
        ]
    )
    
    return {"status": "success"}

@app.delete("/admin/collections/{name}/data/{id}")
async def admin_delete_point(name: str, id: str):
    """Удаление точки"""
    try:
        db_manager.client.delete(
            collection_name=name,
            points_selector=[id]
        )
        # Обновляем счетчик
        db_manager.collections_metadata[name]["record_count"] -= 1
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/admin/import")
async def admin_import_data(req: dict):
    """
    Старт фоновой задачи импорта.
    req: {
        "collection_name": str,
        "data": str (TSV/JSON),
        "mapping": ColumnMapping,
        "recreate": bool
    }
    """
    try:
        # Парсинг данных (упрощенно, ожидаем уже распарсенный JSON для надежности,
        # но по ТЗ фронт парсит, значит сюда придет готовый список)
        # В ТЗ: "POST /admin/upload_data — прием распарсенного JSON с данными"
        # Поэтому сигнатура будет чуть другая
        
        job_id = await job_manager.submit_job("import_batch", req)
        return {"job_id": job_id, "status": "queued"}
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(500, str(e))

@app.get("/admin/jobs")
async def admin_list_jobs():
    return await job_manager.list_jobs()


# === ENDPOINTS ДЛЯ ПОЛУЧЕНИЯ ВСЕХ КОДОВ КСР ИЗ БАЗЫ QDRANT ===
@app.get("/get_all_codes")
async def get_all_codes(database: Optional[str] = None):
    """
    Получение списка ВСЕХ кодов и описаний из коллекции (без пагинации)

    Возвращает словарь {код: описание} для сравнения изменений при обновлении базы.

    Маппинг полей:
    - Qdrant поле "code" → ключ словаря
    - Qdrant поле "description" → значение словаря

    Args:
        database: Название коллекции (если не указано - используется текущая активная)

    Returns:
        {
            "status": "success",
            "collection": "ksr_main",
            "records": {"код1": "описание1", "код2": "описание2", ...},
            "total": 121904,
            "elapsed_seconds": 3.24
        }
    """
    try:
        collection_name = database or db_manager.current_collection

        if not collection_name:
            raise HTTPException(status_code=400, detail="Коллекция не указана")

        logger.info(f"📥 Запрос ВСЕХ кодов и описаний из '{collection_name}'...")
        start_time = time.time()

        loop = asyncio.get_event_loop()

        # Собираем все записи в словарь {код: описание}
        all_records = {}
        offset = None
        batch_count = 0

        # Цикл по всей коллекции батчами
        while True:
            batch_count += 1

            # Запрашиваем батч записей из Qdrant
            scroll_result = await loop.run_in_executor(
                db_manager.executor,
                lambda: db_manager.client.scroll(
                    collection_name=collection_name,
                    limit=10000,  # Внутренний батч для производительности
                    offset=offset,
                    with_payload=[
                        "code",
                        "description",
                    ],  # Только нужные поля из Qdrant
                    with_vectors=False,  # Векторы не нужны (экономия памяти)
                ),
            )

            points, offset = scroll_result

            # Извлекаем код и описание из каждой точки
            for point in points:
                code = point.payload.get("code")
                description = point.payload.get("description")

                if code and description:
                    all_records[code] = description

            # Если offset None - достигли конца коллекции
            if offset is None:
                break

        elapsed = time.time() - start_time

        logger.info(
            f"✅ Собрано {len(all_records)} записей за {elapsed:.2f}с "
            f"({batch_count} батчей)"
        )

        return {
            "status": "success",
            "collection": collection_name,
            "records": all_records,  # Словарь {код: описание}
            "total": len(all_records),
            "elapsed_seconds": round(elapsed, 2),
        }

    except Exception as e:
        logger.error(f"❌ Ошибка получения записей: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Ошибка получения записей: {str(e)}"
        )


# === ENDPOINTS ДЛЯ ОБНОВЛЕНИЯ ДАННЫХ ===
@app.post("/update_record")
async def update_ksr_record(request: UpdateRequest):
    """
    Обновление существующей записи в векторной базе

    Автоматически генерирует новый эмбеддинг для описания
    и обновляет запись в Qdrant без перестроения индекса
    """
    try:
        collection_name = request.database or db_manager.current_collection
        
        # Проверка существования коллекции
        if collection_name not in db_manager.collections_metadata:
            raise HTTPException(
                status_code=404,
                detail=f"Коллекция '{collection_name}' не найдена"
            )
        
        # КРИТИЧНО: Проверяем размерность коллекции vs модели
        collection_dim = db_manager.collections_metadata[collection_name].get("dimension")
        model_dim = db_manager.embedding_model.config.hidden_size
        
        if collection_dim and collection_dim != model_dim:
            raise HTTPException(
                status_code=400,
                detail=f"Размерность коллекции ({collection_dim}) не совпадает с размерностью модели ({model_dim}). "
                       f"Удалите коллекцию '{collection_name}' и создайте заново."
            )

        # Генерация эмбеддинга для нового описания (защищено GPU Lock)
        async with db_manager.gpu_lock:
            new_embedding = await db_manager.get_embedding_cached(request.description)
        
        # Конвертируем numpy array в список для Qdrant
        if isinstance(new_embedding, np.ndarray):
            new_embedding = new_embedding.tolist()

        # Поиск существующей записи по коду
        search_result = db_manager.client.scroll(
            collection_name=collection_name,
            scroll_filter=Filter(
                must=[FieldCondition(key="code", match=MatchValue(value=request.code))]
            ),
            limit=1,
        )

        # Генерируем поля path_level_N для иерархической фильтрации
        path_levels = generate_path_levels(request.description, separator="→")
        
        # Подготовка метаданных
        new_metadata = {
            "code": request.code,
            "description": request.description,
            **path_levels,  # path_level_1, path_level_2, ..., path_depth
            "timestamp": time.time(),
            "source": "manual_update",
        }

        # Обновление записи через менеджер
        # (он сам определит, обновление это или создание новой записи)
        db_manager.update_record(
            code=request.code,
            description=request.description,
            embedding=new_embedding,
            collection_name=collection_name,
            new_metadata=new_metadata
        )
        
        # Обновляем дату последнего изменения
        db_manager.collections_metadata[collection_name]["last_updated"] = datetime.now().strftime("%d.%m.%Y")
        db_manager.save_configuration()
        
        message = f"Запись с кодом '{request.code}' успешно сохранена"

        return {"status": "success", "message": message, "database": collection_name}

    except Exception as e:
        logger.error(f"❌ Ошибка обновления записи: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/update_batch_records")
async def update_ksr_batch(request: BatchUpdateRequest):
    """
    Пакетное обновление записей (Быстрое)
    """
    try:
        collection_name = request.database or db_manager.current_collection
        
        # Преобразуем Pydantic модели в словари
        records_data = [{"code": r.code, "description": r.description} for r in request.records]
        
        logger.info(f"🔄 Получен батч на обновление: {len(records_data)} записей")
        start_time = time.time()
        
        # Выполняем обновление в пуле потоков (т.к. модель блокирующая)
        loop = asyncio.get_event_loop()
        count = await loop.run_in_executor(
            db_manager.executor,
            lambda: db_manager.update_records_batch(records_data, collection_name)
        )
        
        elapsed = time.time() - start_time
        logger.info(f"✅ Батч обработан за {elapsed:.2f}с ({count} записей)")
        
        return {
            "status": "success", 
            "processed": count, 
            "time": elapsed,
            "database": collection_name
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка пакетного обновления: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/delete_batch_records")
async def delete_ksr_batch(request: BatchDeleteRequest):
    """Пакетное удаление записей по кодам"""
    try:
        collection_name = request.database or db_manager.current_collection
        
        deleted_count = db_manager.delete_batch_by_codes(
            codes=request.codes, 
            collection_name=collection_name
        )
        
        return {
            "status": "success",
            "message": f"Удалено {deleted_count} записей из '{collection_name}'",
            "deleted_count": deleted_count
        }

    except Exception as e:
        logger.error(f"❌ Ошибка пакетного удаления: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/delete_record/{code}")
async def delete_ksr_record(code: str, database: Optional[str] = None):
    """Удаление записи из векторной базы по коду КСР"""
    try:
        collection_name = database or db_manager.current_collection

        db_manager.delete_by_code(collection_name=collection_name, code=code)

        return {
            "status": "success",
            "message": f"Записи с кодом '{code}' удалены из '{collection_name}'",
        }

    except Exception as e:
        logger.error(f"❌ Ошибка удаления записи: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# === СБОР АНАЛИТИКИ ===
# FEEDBACK_DIR импортирован из config.py
FEEDBACK_FILE = FEEDBACK_DIR / "positive.jsonl"
DISLIKE_FILE = FEEDBACK_DIR / "negative.jsonl"

# Создание директории и файлов для фидбека
FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
for filepath in [FEEDBACK_FILE, DISLIKE_FILE]:
    if not os.path.exists(filepath):
        open(filepath, "w", encoding="utf-8").close()
        logger.info(f"✅ Создан файл для аналитики: {filepath}")


def clean_text_for_json(text):
    """
    Очистка текста для безопасного сохранения в JSON

    Удаляет управляющие символы и нормализует текст
    """
    if not isinstance(text, str):
        return text

    # Удаляем опасные управляющие символы
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", " ", text)

    # Нормализуем стрелки и разделители
    text = re.sub(r"[→⟶➡➤→>]", " → ", text)
    text = re.sub(r"[\/|\\]", "/", text)

    # Сжимаем пробелы
    text = re.sub(r"\s+", " ", text).strip()

    # Убираем опасные символы (оставляем буквы, цифры, пунктуацию)
    text = re.sub(
        r"[^\w\s\d.,;:!?()\"'«»\[\]{}\-_+=*%#@&$€₽¥£¢§°±→/\\u0400-\u04FF\\u00C0-\u017F]",
        "",
        text,
    )

    return text


@app.post("/feedback/copy")
async def record_copy_event(event: CopyEvent):
    """Записывает событие копирования кода в JSONL файл"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_data = {
            "timestamp": timestamp,
            "query": clean_text_for_json(event.query),
            "selected_code": clean_text_for_json(event.selected_code),
            "position": event.position,
            "description": clean_text_for_json(event.description),
            "database": clean_text_for_json(event.database),
            "reranker_score": event.reranker_score,
            "cosine_similarity": event.cosine_similarity,
        }

        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            json_line = json.dumps(
                cleaned_data, ensure_ascii=False, separators=(",", ":")
            )
            f.write(json_line + "\n")

        logger.info(
            f"📊 Копирование: {cleaned_data['selected_code']} "
            f"(позиция {cleaned_data['position']}, "
            f"rerank: {event.reranker_score:.4f})"
        )

        return {"status": "success", "message": "Событие сохранено"}

    except Exception as e:
        logger.error(f"❌ Ошибка записи события копирования: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка сохранения данных: {str(e)}"
        )


@app.post("/feedback/dislike")
async def record_dislike_event(event: DislikeEvent):
    """Записывает событие дизлайка результата в JSONL файл"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_data = {
            "timestamp": timestamp,
            "query": clean_text_for_json(event.query),
            "selected_code": clean_text_for_json(event.selected_code),
            "position": event.position,
            "description": clean_text_for_json(event.description),
            "database": clean_text_for_json(event.database),
            "reranker_score": event.reranker_score,
            "cosine_similarity": event.cosine_similarity,
            "action": event.action,
        }

        with open(DISLIKE_FILE, "a", encoding="utf-8") as f:
            json_line = json.dumps(
                cleaned_data, ensure_ascii=False, separators=(",", ":")
            )
            f.write(json_line + "\n")

        logger.info(
            f"👎 Дизлайк: {cleaned_data['selected_code']} "
            f"(позиция {cleaned_data['position']})"
        )

        return {"status": "success", "message": "Дизлайк сохранен"}

    except Exception as e:
        logger.error(f"❌ Ошибка записи дизлайка: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка сохранения дизлайка: {str(e)}"
        )


# === ENDPOINT ДЛЯ ПЕРЕЗАГРУЗКИ КОНФИГУРАЦИИ ===
@app.post("/reload_config")
async def reload_config():
    """
    Перезагрузка конфигурации векторных баз без перезапуска сервера

    Использование:
        curl -X POST http://localhost:8000/reload_config

    Или через браузер/Postman:
        POST http://localhost:8000/reload_config

    Returns:
        {
            "status": "success",
            "message": "Конфигурация перезагружена",
            "available_databases": ["ksr_main", "ksr_test"],
            "current_database": "ksr_main",
            "total_databases": 2,
            "changes": {
                "added": ["ksr_test"],
                "removed": [],
                "old_count": 1,
                "new_count": 2
            }
        }
    """
    try:
        logger.info("🔄 Запрос на перезагрузку конфигурации векторных баз...")

        # Запоминаем старое состояние для логирования
        old_databases = set(db_manager.collections_metadata.keys())
        old_count = len(old_databases)

        # Перезагружаем конфиг
        db_manager.load_configuration()

        # Новое состояние
        new_databases = set(db_manager.collections_metadata.keys())
        new_count = len(new_databases)
        current_db = db_manager.current_collection

        # Анализируем изменения
        added = new_databases - old_databases
        removed = old_databases - new_databases

        logger.info(f"✅ Конфигурация перезагружена")
        logger.info(f"📊 Было баз: {old_count}, стало: {new_count}")

        if added:
            logger.info(f"➕ Добавлено баз: {', '.join(added)}")
        if removed:
            logger.info(f"➖ Удалено баз: {', '.join(removed)}")

        return {
            "status": "success",
            "message": "Конфигурация векторных баз перезагружена",
            "available_databases": list(new_databases),
            "current_database": current_db,
            "total_databases": new_count,
            "changes": {
                "added": list(added),
                "removed": list(removed),
                "old_count": old_count,
                "new_count": new_count,
            },
        }

    except Exception as e:
        logger.error(f"❌ Ошибка перезагрузки конфига: {str(e)}")
        import traceback

        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Ошибка перезагрузки конфигурации: {str(e)}"
        )


class CreateCollectionRequest(BaseModel):
    """Запрос на создание новой коллекции"""

    collection_name: str
    dimension: int
    description: str = ""
    recreate: bool = False


@app.post("/create_collection")
async def create_collection(request: CreateCollectionRequest):
    """
    Создание новой коллекции в Qdrant через API

    Args:
        collection_name: Название новой коллекции
        dimension: Размерность векторов
        description: Описание коллекции
        recreate: Удалить существующую если True

    Returns:
        Статус операции
    """
    try:
        from qdrant_client.models import Distance, VectorParams

        logger.info(f"📝 Запрос на создание коллекции: {request.collection_name}")

        # Проверяем существование
        collections = [c.name for c in db_manager.client.get_collections().collections]

        if request.collection_name in collections:
            if request.recreate:
                logger.warning(
                    f"⚠️ Удаление существующей коллекции: {request.collection_name}"
                )
                db_manager.client.delete_collection(request.collection_name)
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Коллекция '{request.collection_name}' уже существует. Используйте recreate=true для перезаписи.",
                )

        # Создаем коллекцию
        # Определяем размерность автоматически из загруженной модели
        model_dimension = db_manager.embedding_model.config.hidden_size
        
        db_manager.client.create_collection(
            collection_name=request.collection_name,
            vectors_config=VectorParams(
                size=model_dimension, distance=Distance.COSINE
            ),
        )

        logger.info(f"✅ Коллекция '{request.collection_name}' создана (dim: {model_dimension})")

        # Обновляем конфигурацию (путь из config.py)
        if VECTOR_DATABASES_CONFIG.exists():
            with open(VECTOR_DATABASES_CONFIG, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

        # Добавляем новую коллекцию с полной конфигурацией
        config[request.collection_name] = {
            "description": request.description or f"Векторная база {request.collection_name}",
            "columns": {"code": "code", "description": "description"},
            "thresholds": {"cosine": 0.45, "rerank": 0.6},
            "last_updated": datetime.now().strftime("%d.%m.%Y"),
            "visible": True,  # По умолчанию видимая
            "locked": False   # По умолчанию не заблокирована
        }

        # Сохраняем конфиг
        with open(VECTOR_DATABASES_CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # Перезагружаем конфигурацию
        db_manager.load_configuration()

        return {
            "status": "success",
            "message": f"Коллекция '{request.collection_name}' успешно создана",
            "collection_name": request.collection_name,
            "dimension": request.dimension,
        }

    except Exception as e:
        logger.error(f"❌ Ошибка создания коллекции: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка создания коллекции: {str(e)}"
        )


@app.post("/upload_batch")
async def upload_batch(collection_name: str, points: List[Dict]):
    """
    Загрузка батча векторов в коллекцию

    Args:
        collection_name: Название коллекции
        points: Список точек с векторами и метаданными
            Формат: [{"id": "uuid", "vector": [...], "payload": {...}}]

    Returns:
        Статус операции
    """
    try:
        from qdrant_client.models import PointStruct

        # Конвертируем в PointStruct
        qdrant_points = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ]

        # Загружаем батч
        db_manager.client.upsert(collection_name=collection_name, points=qdrant_points)

        return {"status": "success", "uploaded": len(points)}

    except Exception as e:
        logger.error(f"❌ Ошибка загрузки батча: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")


# === ЗАПУСК СЕРВЕРА ===
if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 80)
    logger.info("🚀 Запуск сервера KSR Matcher с Qdrant")
    logger.info("=" * 80)
    logger.info(f"📍 Адрес: http://{SERVER_HOST}:{SERVER_PORT}")
    logger.info(f"💾 Хранилище Qdrant: {QDRANT_STORAGE_PATH}")
    logger.info(f"🧠 Модель эмбеддингов: {QWEN_MODEL_PATH}")
    logger.info(f"🎯 Reranker: {RERANKER_PATH}")
    logger.info(f"🖥️ Устройство: {db_manager.device}")
    logger.info(
        f"📚 Доступные коллекции: {list(db_manager.collections_metadata.keys())}"
    )
    logger.info(f"✅ Активная коллекция: {db_manager.current_collection}")
    logger.info("=" * 80)
    logger.info("⚡ Оптимизации:")
    logger.info("   🧠 Кэширование эмбеддингов запросов (15000 записей)")
    logger.info("   🔄 Асинхронная обработка запросов")
    logger.info("   📊 ThreadPoolExecutor для CPU операций")
    logger.info("   🎯 Qdrant с косинусной метрикой (аналог FAISS IndexFlatIP)")
    logger.info("   💾 In-memory производительность с персистентным хранилищем")
    logger.info("   🔤 Регистронезависимый поиск (lowercase нормализация)")
    logger.info("   📦 Встроенное хранение метаданных (без Parquet)")
    logger.info("   🔄 Инкрементальные обновления без перестроения индекса")
    logger.info("=" * 80)

    uvicorn.run(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        workers=1,
        loop="asyncio",
        http="httptools",
        access_log=False,
        log_level="info",
    )
