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
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import httpx
import io
import numpy as np

# Импорт BM25
from text_search import BM25Index
import torch
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
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

# === Библиотеки безопасности ===
from passlib.context import CryptContext  # Хеширование паролей (bcrypt)
from jose import jwt, JWTError  # JWT токены

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# === УТИЛИТЫ ДЛЯ ИЕРАРХИЧЕСКОГО КАТАЛОГА ===
def generate_path_levels(description: str, separator: str = "→") -> dict:
    """
    Генерирует поля path_level_N из иерархического описания.
    
    НОВАЯ ЛОГИКА (v2): Каждый уровень хранит ТОЛЬКО своё название, без контекста.
    Добавлены поля full_description и context_description для разделения данных.
    
    Разбивает description по разделителю и создает набор полей для
    эффективной фильтрации в Qdrant по уровням вложенности.
    
    Пример:
        Input:  "Арматура → Краны → Кран шаровой DN50"
        Output: {
            "path_level_1": "Арматура",           # Только уровень 1
            "path_level_2": "Краны",              # Только уровень 2  
            "path_depth": 2,                      # Глубина категорий (без full_description)
            "full_description": "Кран шаровой DN50",  # Полное описание материала
            "context_description": "Арматура → Краны → Кран шаровой DN50"  # Для эмбеддингов
        }
    
    Args:
        description (str): Полное описание с иерархией, разделенной separator.
        separator (str): Разделитель уровней иерархии (по умолчанию "→").
    
    Returns:
        dict: Словарь с полями path_level_1..N, path_depth, full_description, context_description.
    """
    # Сохраняем полный контекст для эмбеддингов
    context_description = description.strip()
    
    # Если нет разделителя в строке - это только описание материала без категорий
    if separator not in description:
        return {
            "path_depth": 0,  # Нет уровней категорий
            "full_description": context_description,
            "context_description": context_description
        }
    
    # Разбиваем по разделителю и очищаем от лишних пробелов
    parts = [part.strip() for part in description.split(separator)]
    # Фильтруем пустые части (на случай двойных разделителей)
    parts = [p for p in parts if p]
    
    if not parts:
        return {
            "path_depth": 0,
            "full_description": "",
            "context_description": context_description
        }
    
    # Последняя часть - это полное описание материала
    # Все предыдущие части - уровни категорий
    full_description = parts[-1] if parts else ""
    category_parts = parts[:-1] if len(parts) > 1 else []
    
    result = {
        "path_depth": len(category_parts),  # Глубина = количество категорий
        "full_description": full_description,
        "context_description": context_description
    }
    
    # Генерируем path_level_1, path_level_2, ... path_level_N
    # Каждый уровень содержит ТОЛЬКО своё название (без контекста предыдущих)
    for i, part in enumerate(category_parts):
        result[f"path_level_{i + 1}"] = part
    
    return result


def generate_path_levels_combined(hierarchy: str, description: str, separator: str = "→") -> dict:
    """
    Генерирует поля path_level_N комбинируя иерархию (папки) и описание (материал).
    
    НОВАЯ ЛОГИКА (v2): Каждый уровень категории хранится отдельно.
    Используется когда пользователь настроил отдельную иерархию для каталога
    и отдельное описание для материала.
    
    Пример:
        hierarchy:    "Арматура → Краны"
        description:  "Кран шаровой DN50 PN16"
        
        Output: {
            "path_level_1": "Арматура",           # Только уровень 1
            "path_level_2": "Краны",              # Только уровень 2
            "path_depth": 2,                      # Глубина категорий
            "full_description": "Кран шаровой DN50 PN16",  # Полное описание материала
            "context_description": "Арматура → Краны → Кран шаровой DN50 PN16"  # Для эмбеддингов
        }
    
    Если hierarchy совпадает с description или пустой - использует стандартную логику.
    
    Args:
        hierarchy (str): Строка категорий для папок каталога (разделённая separator).
        description (str): Полное описание материала (название элемента).
        separator (str): Разделитель уровней иерархии (по умолчанию "→").
    
    Returns:
        dict: Словарь с полями path_level_1..N, path_depth, full_description, context_description.
    """
    # Если иерархия не указана или совпадает с описанием - стандартная логика
    if not hierarchy or hierarchy == description:
        return generate_path_levels(description, separator)
    
    # Разбиваем иерархию на части (это категории/папки)
    hierarchy_parts = [part.strip() for part in hierarchy.split(separator)]
    hierarchy_parts = [p for p in hierarchy_parts if p]
    
    if not hierarchy_parts:
        return generate_path_levels(description, separator)
    
    # Полное описание материала
    full_description = description.strip()
    
    # Формируем контекстное описание для эмбеддингов: категории + описание
    # ВАЖНО: Cобираем все части и соединяем через разделитель, убирая пустые
    parts_to_join = hierarchy_parts + [full_description]
    parts_to_join = [p for p in parts_to_join if p] # Фильтруем пустые части
    
    if not parts_to_join:
        context_description = "пусто" # Fallback если всё очистилось
    else:
        context_description = f" {separator} ".join(parts_to_join)
    
    result = {
        "path_depth": len(hierarchy_parts),  # Глубина = количество категорий
        "full_description": full_description,
        "context_description": context_description
    }
    
    # Генерируем уровни категорий - каждый содержит ТОЛЬКО своё название
    for i, part in enumerate(hierarchy_parts):
        result[f"path_level_{i + 1}"] = part
    
    return result


def extract_folders_from_records(all_path_levels: list, separator: str = "→") -> list:
    """
    Извлекает уникальные папки (категории) из списка path_levels материалов.
    
    Для каждого уникального пути категории создаётся запись с:
    - full_path: полный путь категории (для генерации эмбеддинга)
    - leaf_name: название конечной папки (для rerank)
    - level: уровень вложенности
    - items_count: количество материалов в этой категории
    
    Пример:
        Input: [
            {"path_level_1": "Арматура", "path_level_2": "Краны", "path_depth": 2, ...},
            {"path_level_1": "Арматура", "path_level_2": "Задвижки", "path_depth": 2, ...},
            {"path_level_1": "Арматура", "path_level_2": "Краны", "path_depth": 2, ...},
        ]
        
        Output: [
            {"full_path": "Арматура", "leaf_name": "Арматура", "level": 1, "items_count": 3, 
             "path_levels": {"path_level_1": "Арматура"}},
            {"full_path": "Арматура → Краны", "leaf_name": "Краны", "level": 2, "items_count": 2,
             "path_levels": {"path_level_1": "Арматура", "path_level_2": "Краны"}},
            {"full_path": "Арматура → Задвижки", "leaf_name": "Задвижки", "level": 2, "items_count": 1,
             "path_levels": {"path_level_1": "Арматура", "path_level_2": "Задвижки"}},
        ]
    
    Args:
        all_path_levels (list): Список словарей path_levels из материалов.
        separator (str): Разделитель для формирования full_path (по умолчанию "→").
    
    Returns:
        list: Список уникальных папок с метаданными.
    """
    # Словарь для подсчёта уникальных путей категорий
    # Ключ: tuple путей (для хеширования), Значение: {count, path_parts}
    folder_counts = {}
    
    for path_data in all_path_levels:
        path_depth = path_data.get("path_depth", 0)
        
        # Пропускаем записи без категорий
        if path_depth == 0:
            continue
        
        # Собираем все уровни категорий
        path_parts = []
        for level in range(1, path_depth + 1):
            level_key = f"path_level_{level}"
            if level_key in path_data and path_data[level_key]:
                path_parts.append(path_data[level_key])
            else:
                break  # Прерываем, если уровень отсутствует
        
        # Для каждого уровня вложенности создаём отдельную папку
        # Например, для "Арматура → Краны → Шаровые" создаём:
        # - "Арматура" (level 1)
        # - "Арматура → Краны" (level 2)
        # - "Арматура → Краны → Шаровые" (level 3)
        # 
        # ВАЖНО: items_count увеличиваем только для КОНЕЧНОЙ папки материала!
        # Родительские папки не содержат материал напрямую.
        total_levels = len(path_parts)
        
        for level in range(1, total_levels + 1):
            current_parts = tuple(path_parts[:level])
            
            if current_parts not in folder_counts:
                folder_counts[current_parts] = {
                    "count": 0,
                    "parts": list(current_parts)
                }
            
            # Увеличиваем count ТОЛЬКО для конечной папки (последний уровень)
            # Родительские папки не содержат материал напрямую
            if level == total_levels:
                folder_counts[current_parts]["count"] += 1
    
    # Формируем результат
    folders = []
    for path_tuple, data in folder_counts.items():
        parts = data["parts"]
        level = len(parts)
        
        # full_path - полный путь для эмбеддинга (с контекстом)
        full_path = f" {separator} ".join(parts)
        
        # leaf_name - название конечной папки (для rerank)
        leaf_name = parts[-1] if parts else ""
        
        # Формируем path_levels для записи в Qdrant
        path_levels_dict = {}
        for i, part in enumerate(parts):
            path_levels_dict[f"path_level_{i + 1}"] = part
        
        folders.append({
            "full_path": full_path,
            "leaf_name": leaf_name,
            "level": level,
            "items_count": data["count"],
            "path_levels": path_levels_dict
        })
    
    # Сортируем по уровню и затем по имени
    folders.sort(key=lambda x: (x["level"], x["full_path"]))
    
    logger.info(f"📁 Извлечено {len(folders)} уникальных папок из {len(all_path_levels)} материалов")
    
    return folders


def build_full_path_from_payload(payload: dict, separator: str = " → ") -> str:
    """
    Восстанавливает полный путь папки из path_level_N полей в payload.
    
    Пример:
        payload = {"path_level_1": "Приборы", "path_level_2": "Аннотации", "path_depth": 2}
        → "Приборы → Аннотации"
    
    Args:
        payload: Словарь с path_level_N и path_depth
        separator: Разделитель уровней (по умолчанию " → ")
    
    Returns:
        Полный путь или пустая строка
    """
    path_depth = payload.get("path_depth", 0)
    if not path_depth:
        return ""
    
    parts = []
    for i in range(1, path_depth + 1):
        part = payload.get(f"path_level_{i}", "")
        if part:
            parts.append(part)
        else:
            break  # Прерываем если уровень пустой
    
    return separator.join(parts)


async def sync_folders_after_material_edit(
    db_manager,
    collection_name: str,
    old_folder_ids: list,
    new_folder_ids: list,
    old_paths: list,
    new_paths: list
) -> dict:
    """
    Синхронизация записей папок после редактирования материала.
    
    УЛУЧШЕННАЯ ЛОГИКА:
    1. Если leaf_name папки тот же, но путь изменился (родитель переименован) - ОБНОВЛЯЕМ папку
    2. Если папка осиротела (нет материалов) - удаляем
    3. Если действительно новая папка (новый leaf_name) - создаём
    
    Args:
        db_manager: Менеджер базы данных
        collection_name: Имя коллекции
        old_folder_ids: Список ID папок ДО изменения
        new_folder_ids: Список ID папок ПОСЛЕ изменения
        old_paths: Список путей папок ДО изменения
        new_paths: Список путей папок ПОСЛЕ изменения
    
    Returns:
        Словарь с результатами {created: [], deleted: [], updated: []}
    """
    result = {"created": [], "deleted": [], "updated": []}
    
    if old_folder_ids == new_folder_ids and old_paths == new_paths:
        return result  # Ничего не изменилось
    
    columns = db_manager.collections_metadata[collection_name]["columns"]
    code_field = columns["code"]
    
    # Создаём маппинг: leaf_name -> (old_id, old_path) и (new_id, new_path)
    old_leaves = {}  # {leaf_name: (id, full_path, index)}
    new_leaves = {}  # {leaf_name: (id, full_path, index)}
    
    for i, (fid, path) in enumerate(zip(old_folder_ids or [], old_paths or [])):
        leaf = path.split(" → ")[-1] if path else ""
        old_leaves[leaf] = (fid, path, i)
    
    for i, (fid, path) in enumerate(zip(new_folder_ids or [], new_paths or [])):
        leaf = path.split(" → ")[-1] if path else ""
        new_leaves[leaf] = (fid, path, i)
    
    # === ОПРЕДЕЛЯЕМ ТИПЫ ИЗМЕНЕНИЙ ПО LEAF_NAME ===
    old_leaf_names = set(old_leaves.keys())
    new_leaf_names = set(new_leaves.keys())
    
    # Папки с тем же leaf_name - нужно ОБНОВИТЬ (путь изменился из-за родителя)
    leaves_to_update = old_leaf_names & new_leaf_names
    # Новые leaf_name - создать
    leaves_to_create = new_leaf_names - old_leaf_names
    # Удалённые leaf_name - проверить на осиротевшие
    leaves_to_delete = old_leaf_names - new_leaf_names
    
    # === 1. ОБНОВЛЯЕМ ПАПКИ, ГДЕ ИЗМЕНИЛСЯ ПУТЬ (родитель переименован) ===
    for leaf in leaves_to_update:
        old_id, old_path, _ = old_leaves[leaf]
        new_id, new_path, _ = new_leaves[leaf]
        
        if old_id == new_id:
            continue  # Путь не изменился
        
        # Путь изменился - нужно переместить папку
        # Получаем старую папку
        old_folder = db_manager.client.retrieve(
            collection_name=collection_name,
            ids=[old_id],
            with_payload=True,
            with_vectors=False
        )
        
        if old_folder:
            old_payload = dict(old_folder[0].payload)
            new_parts = new_path.split(" → ")
            new_folder_code = f"folder::{new_path.replace(' → ', '::')}"
            
            # Генерируем новый эмбеддинг для нового пути
            async with db_manager.gpu_lock:
                emb = await db_manager.get_embedding_cached(new_path)
                vector = emb.tolist() if isinstance(emb, np.ndarray) else emb
            
            # Формируем новый path_levels
            path_levels = {}
            for i, part in enumerate(new_parts):
                path_levels[f"path_level_{i + 1}"] = part
            
            # Обновляем payload
            new_payload = {
                **old_payload,
                code_field: new_folder_code,
                columns["description"]: new_path,
                "full_path": new_path,
                "timestamp": time.time(),
                "source": "material_edit_path_update",
                **path_levels
            }
            
            # Удаляем старую папку
            db_manager.client.delete(
                collection_name=collection_name,
                points_selector=[old_id]
            )
            
            # Создаём с новым ID и обновлённым путём
            db_manager.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=new_id,
                        vector=vector,
                        payload=new_payload
                    )
                ]
            )
            result["updated"].append({"old_path": old_path, "new_path": new_path, "leaf_name": leaf})
            logger.info(f"📁 Обновлён путь папки '{leaf}': {old_path} → {new_path}")
    
    # === 2. ПРОВЕРЯЕМ И УДАЛЯЕМ ОСИРОТЕВШИЕ ПАПКИ ===
    for leaf in leaves_to_delete:
        old_id, old_path, _ = old_leaves[leaf]
        old_parts = old_path.split(" → ")
        
        # Подсчитываем материалы с этим путём
        filter_conditions = []
        for i, part in enumerate(old_parts):
            filter_conditions.append(
                FieldCondition(
                    key=f"path_level_{i + 1}",
                    match=MatchValue(value=part)
                )
            )
        
        try:
            count_result = db_manager.client.count(
                collection_name=collection_name,
                count_filter=Filter(
                    must=filter_conditions,
                    must_not=[
                        FieldCondition(
                            key="is_folder",
                            match=MatchValue(value=True)
                        )
                    ]
                )
            )
            materials_count = count_result.count
        except Exception as e:
            logger.warning(f"⚠️ Не удалось подсчитать материалы для '{old_path}': {e}")
            materials_count = 1
        
        if materials_count == 0:
            # Папка осиротела - удаляем
            try:
                db_manager.client.delete(
                    collection_name=collection_name,
                    points_selector=[old_id]
                )
                result["deleted"].append(old_path)
                logger.info(f"🗑️ Удалена осиротевшая папка: {old_path}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось удалить папку '{old_path}': {e}")
    
    # === 3. СОЗДАЁМ НОВЫЕ ПАПКИ (только действительно новые leaf_name) ===
    for leaf in leaves_to_create:
        new_id, new_path, _ = new_leaves[leaf]
        new_parts = new_path.split(" → ")
        
        # Проверяем существование
        existing = db_manager.client.retrieve(
            collection_name=collection_name,
            ids=[new_id],
            with_payload=True,
            with_vectors=False
        )
        
        if not existing:
            new_leaf_name = new_parts[-1] if new_parts else ""
            folder_code = f"folder::{new_path.replace(' → ', '::')}"
            
            # Генерируем эмбеддинг
            async with db_manager.gpu_lock:
                emb = await db_manager.get_embedding_cached(new_path)
                vector = emb.tolist() if isinstance(emb, np.ndarray) else emb
            
            path_levels = {}
            for i, part in enumerate(new_parts):
                path_levels[f"path_level_{i + 1}"] = part
            
            payload = {
                code_field: folder_code,
                columns["description"]: new_path,
                "full_path": new_path,
                "leaf_name": new_leaf_name,
                "path_depth": len(new_parts),
                "items_count": 1,
                "is_folder": True,
                "timestamp": time.time(),
                "source": "material_edit_sync",
                **path_levels
            }
            
            db_manager.client.upsert(
                collection_name=collection_name,
                points=[
                    PointStruct(
                        id=new_id,
                        vector=vector,
                        payload=payload
                    )
                ]
            )
            result["created"].append(new_path)
            logger.info(f"📁 Создана новая папка: {new_path}")
    
    return result


# Старая функция для обратной совместимости
async def sync_folder_after_material_edit(
    db_manager,
    collection_name: str,
    old_path: str,
    new_path: str
) -> dict:
    """
    DEPRECATED: Используйте sync_folders_after_material_edit вместо этой функции.
    Оставлена для обратной совместимости.
    """
    # Вычисляем folder_ids и paths для новой функции
    old_folder_ids = []
    old_paths = []
    new_folder_ids = []
    new_paths = []
    
    if old_path:
        old_parts = old_path.split(" → ")
        for i in range(1, len(old_parts) + 1):
            path = " → ".join(old_parts[:i])
            folder_code = f"folder::{path.replace(' → ', '::')}"
            folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
            old_folder_ids.append(folder_id)
            old_paths.append(path)
    
    if new_path:
        new_parts = new_path.split(" → ")
        for i in range(1, len(new_parts) + 1):
            path = " → ".join(new_parts[:i])
            folder_code = f"folder::{path.replace(' → ', '::')}"
            folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
            new_folder_ids.append(folder_id)
            new_paths.append(path)
    
    return await sync_folders_after_material_edit(
        db_manager, collection_name, 
        old_folder_ids, new_folder_ids,
        old_paths, new_paths
    )


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
    API_EMBEDDING_BATCH_SIZE,
    API_MAX_WORKERS,
    SERVER_HOST,
    SERVER_PORT,
    # Настройки безопасности админ-панели
    ADMIN_PASSWORD_HASH,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRE_HOURS,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_LOCKOUT_MINUTES,
    # Гибридный поиск (BM25)
    BM25_ENABLED,
    BM25_TOP_K,
    BM25_MAX_RETRIEVE,
    HYBRID_RERANK_LIMIT,
)

# Базовая директория скрипта (для обратной совместимости)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# === БЕЗОПАСНОСТЬ: Контекст хеширования паролей ===
# Используем bcrypt - современный алгоритм с адаптивной сложностью
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# === БЕЗОПАСНОСТЬ: Защита от брутфорса ===
class LoginRateLimiter:
    """
    Ограничитель частоты попыток входа (Rate Limiter).
    
    Защищает от атак перебором паролей (brute-force).
    После превышения лимита попыток IP блокируется на заданное время.
    
    Алгоритм:
    1. При каждой попытке входа записывается timestamp по IP.
    2. Удаляются старые записи (старше lockout_seconds).
    3. Если количество попыток >= max_attempts, вход блокируется.
    
    Attributes:
        attempts (dict): Словарь {ip: [timestamp1, timestamp2, ...]}.
        max_attempts (int): Максимальное количество попыток.
        lockout_seconds (int): Время блокировки в секундах.
    """
    
    def __init__(self, max_attempts: int = 5, lockout_minutes: int = 5):
        """
        Инициализация Rate Limiter.
        
        Args:
            max_attempts: Максимальное количество попыток (по умолчанию 5).
            lockout_minutes: Время блокировки в минутах (по умолчанию 5).
        """
        self.attempts: Dict[str, List[float]] = {}
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_minutes * 60
        self.lock = asyncio.Lock()
    
    async def is_blocked(self, ip: str) -> bool:
        """
        Проверка, заблокирован ли IP.
        
        Args:
            ip: IP-адрес клиента.
            
        Returns:
            bool: True если IP заблокирован.
        """
        async with self.lock:
            if ip not in self.attempts:
                return False
            
            now = time.time()
            # Удаляем старые попытки (старше lockout_seconds)
            self.attempts[ip] = [
                t for t in self.attempts[ip]
                if now - t < self.lockout_seconds
            ]
            
            # Проверяем количество попыток
            return len(self.attempts[ip]) >= self.max_attempts
    
    async def record_attempt(self, ip: str):
        """
        Записывает попытку входа.
        
        Args:
            ip: IP-адрес клиента.
        """
        async with self.lock:
            if ip not in self.attempts:
                self.attempts[ip] = []
            
            self.attempts[ip].append(time.time())
            
            # Логируем при приближении к лимиту
            count = len(self.attempts[ip])
            if count >= self.max_attempts - 1:
                logger.warning(
                    f"⚠️ Rate limit: IP {ip} - {count}/{self.max_attempts} попыток"
                )
    
    async def clear(self, ip: str):
        """
        Очищает историю попыток для IP (после успешного входа).
        
        Args:
            ip: IP-адрес клиента.
        """
        async with self.lock:
            if ip in self.attempts:
                del self.attempts[ip]
    
    def get_remaining_time(self, ip: str) -> int:
        """
        Возвращает оставшееся время блокировки в секундах.
        
        Args:
            ip: IP-адрес клиента.
            
        Returns:
            int: Секунд до разблокировки (0 если не заблокирован).
        """
        if ip not in self.attempts or not self.attempts[ip]:
            return 0
        
        oldest_attempt = min(self.attempts[ip])
        remaining = self.lockout_seconds - (time.time() - oldest_attempt)
        return max(0, int(remaining))


# Глобальный экземпляр Rate Limiter
login_rate_limiter = LoginRateLimiter(
    max_attempts=LOGIN_MAX_ATTEMPTS,
    lockout_minutes=LOGIN_LOCKOUT_MINUTES
)


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
        
        НОВАЯ ЛОГИКА v2: Поддержка нового формата path_level_N.
        
        Новый формат:
        - path_level_N содержит ТОЛЬКО название уровня (не накопительный путь)
        - full_description содержит полное описание материала
        - Категории определяются по path_level_1..N
        - Материалы определяются по full_description
        
        Алгоритм:
        1. Scroll по всем записям, собирая path_level_N и full_description.
        2. Агрегация уникальных комбинаций путей (parent_key -> children).
        3. Рекурсивное построение дерева.
        
        Args:
            client: Клиент Qdrant.
            collection_name: Имя коллекции.
            separator: Разделитель уровней.
            max_depth: Максимальная глубина.
            
        Returns:
            dict: {tree: [...], stats: {...}}.
        """
        # Структура для агрегации:
        # categories: {full_path: {name, count, children_paths, has_materials}}
        # materials: {parent_path: [{code, full_description}]}
        categories = {}  # {full_path_tuple: {name, level, count, parent_path}}
        materials_by_parent = {}  # {parent_path_tuple: [{code, full_description}]}
        total_items = 0
        max_found_depth = 0
        
        # Scroll по всем записям
        offset = None
        batch_size = 1000
        
        while True:
            # Запрашиваем path_level_N, path_depth, full_description и код
            payload_fields = [f"path_level_{i}" for i in range(1, max_depth + 1)]
            payload_fields.extend(["path_depth", "code", "full_description", "description"])
            
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
                
                # Получаем глубину категорий (не включая материал)
                depth = payload.get("path_depth", 0)
                code = payload.get("code", "")
                full_desc = payload.get("full_description", "")
                max_found_depth = max(max_found_depth, depth)
                
                # Собираем путь категорий как кортеж
                path_parts = []
                for level in range(1, depth + 1):
                    level_value = payload.get(f"path_level_{level}", "")
                    if level_value:
                        path_parts.append(level_value)
                    else:
                        break
                
                # Регистрируем все уровни категорий
                for i in range(len(path_parts)):
                    level = i + 1
                    current_path = tuple(path_parts[:level])
                    parent_path = tuple(path_parts[:level-1]) if level > 1 else ()
                    
                    if current_path not in categories:
                        categories[current_path] = {
                            "name": path_parts[i],
                            "level": level,
                            "count": 0,
                            "parent_path": parent_path,
                            "has_materials": False
                        }
                    categories[current_path]["count"] += 1
                
                # Регистрируем материал (full_description)
                if full_desc:
                    parent_path = tuple(path_parts) if path_parts else ()
                    if parent_path not in materials_by_parent:
                        materials_by_parent[parent_path] = []
                    
                    # Ограничиваем количество материалов для preview
                    if len(materials_by_parent[parent_path]) < 10:
                        materials_by_parent[parent_path].append({
                            "code": code,
                            "full_description": full_desc
                        })
                    
                    # Помечаем родительскую категорию как имеющую материалы
                    if parent_path in categories:
                        categories[parent_path]["has_materials"] = True
            
            offset = next_offset
            if offset is None:
                break
        
        # Строим дерево из агрегированных данных
        tree = self._build_tree_structure_v2(categories, materials_by_parent, separator, max_depth)
        
        # Подсчёт статистики
        total_categories = len(categories)
        total_materials = sum(len(m) for m in materials_by_parent.values())
        
        return {
            "tree": tree,
            "stats": {
                "total_categories": total_categories,
                "total_items": total_items,
                "total_materials": total_materials,
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
    
    def _build_tree_structure_v2(
        self,
        categories: dict,
        materials_by_parent: dict,
        separator: str,
        max_depth: int
    ) -> List[dict]:
        """
        Построение древовидной структуры из нового формата данных (v2).
        
        НОВАЯ ЛОГИКА:
        - categories: {path_tuple: {name, level, count, parent_path, has_materials}}
        - materials_by_parent: {parent_path_tuple: [{code, full_description}]}
        - Материалы отображаются как листовые элементы с флагом is_material=True
        
        Args:
            categories: Словарь категорий.
            materials_by_parent: Словарь материалов по родительскому пути.
            separator: Разделитель уровней.
            max_depth: Максимальная глубина.
            
        Returns:
            List[dict]: Список корневых узлов дерева.
        """
        def build_path_string(path_tuple: tuple) -> str:
            """Формирует строку пути из кортежа для отображения."""
            return f" {separator} ".join(path_tuple) if path_tuple else ""
        
        def build_children(parent_path: tuple, current_level: int) -> List[dict]:
            """Рекурсивное построение детей для узла."""
            if current_level >= max_depth:
                return []
            
            children = []
            next_level = current_level + 1
            
            # Ищем категории-дети (те, у которых parent_path == текущий path)
            for path_tuple, cat_data in categories.items():
                if cat_data["parent_path"] == parent_path and cat_data["level"] == next_level:
                    path_str = build_path_string(path_tuple)
                    
                    node = {
                        "name": cat_data["name"],
                        "path": path_str,
                        "level": next_level,
                        "count": cat_data["count"],
                        "is_category": True,
                        "has_materials": cat_data["has_materials"],
                        "children": build_children(path_tuple, next_level)
                    }
                    
                    # Добавляем материалы для этой категории (если есть и нет дочерних категорий)
                    if path_tuple in materials_by_parent:
                        materials = materials_by_parent[path_tuple]
                        # Если нет дочерних категорий - показываем материалы как children
                        if not node["children"] and materials:
                            node["materials"] = [
                                {
                                    "name": m["full_description"],
                                    "code": m["code"],
                                    "is_material": True
                                }
                                for m in materials[:5]
                            ]
                            node["materials_count"] = len(materials_by_parent.get(path_tuple, []))
                    
                    children.append(node)
            
            # Сортируем по имени
            children.sort(key=lambda x: x["name"])
            return children
        
        # Строим корневые узлы (уровень 1)
        root_nodes = []
        
        for path_tuple, cat_data in categories.items():
            if cat_data["level"] == 1:
                path_str = build_path_string(path_tuple)
                
                node = {
                    "name": cat_data["name"],
                    "path": path_str,
                    "level": 1,
                    "count": cat_data["count"],
                    "is_category": True,
                    "has_materials": cat_data["has_materials"],
                    "children": build_children(path_tuple, 1)
                }
                
                # Добавляем материалы для корневой категории (если нет дочерних)
                if path_tuple in materials_by_parent:
                    materials = materials_by_parent[path_tuple]
                    if not node["children"] and materials:
                        node["materials"] = [
                            {
                                "name": m["full_description"],
                                "code": m["code"],
                                "is_material": True
                            }
                            for m in materials[:5]
                        ]
                        node["materials_count"] = len(materials_by_parent.get(path_tuple, []))
                
                root_nodes.append(node)
        
        # Добавляем материалы без категорий (если есть)
        if () in materials_by_parent:
            uncategorized = materials_by_parent[()]
            for m in uncategorized[:10]:
                root_nodes.append({
                    "name": m["full_description"],
                    "code": m["code"],
                    "path": "",
                    "level": 0,
                    "count": 1,
                    "is_material": True,
                    "is_category": False
                })
        
        # Сортируем: сначала категории, потом материалы, по имени
        root_nodes.sort(key=lambda x: (not x.get("is_category", False), x["name"]))
        
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
        Прямое получение дочерних категорий и материалов без построения полного дерева.
        
        НОВАЯ ЛОГИКА v2: Поддержка нового формата path_level_N.
        ИСПРАВЛЕНО: Тяжёлая операция scroll выполняется в ThreadPoolExecutor,
        чтобы не блокировать event loop и позволять обрабатывать другие запросы параллельно.
        
        В новом формате:
        - path_level_N содержит ТОЛЬКО название уровня (не накопительный путь)
        - parent_path передаётся как полный путь "Арматура → Краны"
        - Материалы определяются по full_description
        
        Args:
            client: Клиент Qdrant.
            collection_name: Имя коллекции.
            parent_path: Полный путь родительской категории (пустой = корень).
            parent_level: Уровень родителя (0 = корень, дети будут уровня 1).
            separator: Разделитель уровней.
            
        Returns:
            dict: {children: [...], materials: [...], parent_path: str, total: int, cached: bool}
        """
        # Ключ кэша включает путь родителя
        cache_key = f"{collection_name}_children_v2_{parent_level}_{parent_path}"
        
        # Проверяем кэш прямых детей (TTL 5 минут)
        if cache_key in self.children_cache:
            cache_entry = self.children_cache[cache_key]
            age = time.time() - cache_entry["timestamp"]
            if age < self.cache_ttl:
                logger.debug(f"📦 Children cache hit: {cache_key[:50]}...")
                return {
                    "children": cache_entry.get("children", []),
                    "materials": cache_entry.get("materials", []),
                    "parent_path": parent_path,
                    "total": cache_entry.get("total", 0),
                    "cached": True,
                    "cache_age": int(age)
                }
        
        # Разбираем родительский путь на части
        parent_parts = [p.strip() for p in parent_path.split(separator) if p.strip()] if parent_path else []
        
        # Уровень детей = уровень родителя + 1
        child_level = parent_level + 1
        child_level_field = f"path_level_{child_level}"
        
        logger.info(f"🔍 Direct children load v2: parent='{parent_path[:50] if parent_path else 'ROOT'}' level={child_level}")
        start_time = time.time()
        
        # Формируем фильтр по всем уровням родительского пути
        filter_conditions = []
        for i, part in enumerate(parent_parts):
            filter_conditions.append(
                FieldCondition(
                    key=f"path_level_{i + 1}",
                    match=MatchValue(value=part)
                )
            )
        
        scroll_filter = Filter(must=filter_conditions) if filter_conditions else None
        
        # === СИНХРОННАЯ ФУНКЦИЯ ДЛЯ ВЫПОЛНЕНИЯ В ОТДЕЛЬНОМ ПОТОКЕ ===
        # Scroll по Qdrant - блокирующая операция, выносим в ThreadPoolExecutor
        def _scroll_and_aggregate():
            """Выполняет scroll и агрегацию в отдельном потоке (не блокирует event loop)"""
            children_data = {}
            materials_data = []
            offset = None
            batch_size = 1000
            total_scanned = 0
            
            while True:
                # Запрашиваем нужные поля
                payload_fields = [f"path_level_{i}" for i in range(1, child_level + 2)]
                payload_fields.extend(["code", "path_depth", "full_description"])
                
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
                    depth = payload.get("path_depth", 0)
                    code = payload.get("code", "")
                    full_desc = payload.get("full_description", "")
                    
                    # Получаем значение на уровне детей
                    child_value = payload.get(child_level_field)
                    next_level_value = payload.get(f"path_level_{child_level + 1}")
                    
                    # Проверяем, что родительский путь соответствует
                    parent_matches = True
                    for i, part in enumerate(parent_parts):
                        if payload.get(f"path_level_{i + 1}") != part:
                            parent_matches = False
                            break
                    
                    if not parent_matches:
                        continue
                    
                    if child_value:
                        # Есть дочерняя категория
                        if child_value not in children_data:
                            children_data[child_value] = {
                                "count": 0,
                                "has_children": False,
                                "codes": [],
                                "materials": []
                            }
                        
                        children_data[child_value]["count"] += 1
                        
                        # Проверяем наличие следующего уровня
                        if next_level_value:
                            children_data[child_value]["has_children"] = True
                        
                        # Собираем коды и материалы для категории
                        if code and len(children_data[child_value]["codes"]) < 5:
                            children_data[child_value]["codes"].append(code)
                        
                        # Если это листовая категория (depth == child_level) и есть full_description
                        if depth == child_level and full_desc:
                            if len(children_data[child_value]["materials"]) < 5:
                                children_data[child_value]["materials"].append({
                                    "code": code,
                                    "name": full_desc
                                })
                    
                    elif depth == parent_level and full_desc:
                        # Материал без дочерней категории (прямой потомок родителя)
                        if len(materials_data) < 50:
                            materials_data.append({
                                "code": code,
                                "name": full_desc,
                                "is_material": True
                            })
                
                offset = next_offset
                if offset is None:
                    break
            
            return children_data, materials_data, total_scanned
        
        # === ВЫПОЛНЯЕМ ТЯЖЁЛУЮ ОПЕРАЦИЮ В ОТДЕЛЬНОМ ПОТОКЕ ===
        # Используем глобальный executor из db_manager (если доступен) или создаём свой
        loop = asyncio.get_event_loop()
        
        # Получаем executor - используем тот же что и для поиска
        from concurrent.futures import ThreadPoolExecutor
        executor = getattr(db_manager, 'executor', None) or ThreadPoolExecutor(max_workers=2)
        
        children_data, materials_data, total_scanned = await loop.run_in_executor(
            executor, _scroll_and_aggregate
        )
        
        # Формируем список дочерних категорий (это быстрая операция, можно в main thread)
        children = []
        for name, data in children_data.items():
            # Формируем полный путь для ребёнка
            child_path = f"{parent_path} {separator} {name}" if parent_path else name
            
            child = {
                "name": name,
                "path": child_path,
                "level": child_level,
                "count": data["count"],
                "has_children": data["has_children"],
                "is_category": True
            }
            
            # Добавляем материалы если нет дочерних категорий
            if data["materials"] and not data["has_children"]:
                child["materials"] = data["materials"]
                child["has_materials"] = True
            
            # Добавляем коды если нет дочерних категорий и нет материалов
            if data["codes"] and not data["has_children"] and not data["materials"]:
                if len(data["codes"]) == 1:
                    child["code"] = data["codes"][0]
                else:
                    child["codes"] = data["codes"]
            
            children.append(child)
        
        # Сортируем по имени
        children.sort(key=lambda x: x["name"])
        materials_data.sort(key=lambda x: x["name"])
        
        elapsed = time.time() - start_time
        logger.info(
            f"✅ Direct children loaded v2 in {elapsed:.2f}s: "
            f"{len(children)} categories, {len(materials_data)} materials, scanned {total_scanned} records"
        )
        
        # Сохраняем в кэш
        self.children_cache[cache_key] = {
            "children": children,
            "materials": materials_data,
            "total": len(children) + len(materials_data),
            "timestamp": time.time()
        }
        
        return {
            "children": children,
            "materials": materials_data,
            "parent_path": parent_path,
            "total": len(children) + len(materials_data),
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
        
        # Индексы BM25 {collection_name: BM25Index}
        self.bm25_indices: Dict[str, BM25Index] = {}

        # Текущая активная коллекция (исключаем _settings)
        # Получаем только реальные коллекции (не служебные секции)
        real_collections = {
            name: meta for name, meta in self.collections_metadata.items()
            if name != "_settings"
        }
        self.current_collection = (
            next(iter(real_collections)) if real_collections else None
        )
        
        # Дополнительная проверка: если по какой-то причине current_collection = "_settings", исправляем
        if self.current_collection == "_settings":
            self.current_collection = (
                next(iter(real_collections)) if real_collections else None
            )

        if self.current_collection:
            logger.info(f"🎯 Активная коллекция: {self.current_collection}")
        else:
            logger.warning("⚠️ Нет доступных коллекций в Qdrant")

        # === ЛЕНИВАЯ ИНИЦИАЛИЗАЦИЯ МОДЕЛИ ЭМБЕДДИНГОВ ===
        # Модель НЕ загружается при старте - только при первом использовании
        # Это экономит GPU память, если используется OpenRouter API
        self._embedding_model_loaded = False
        self.embedding_model = None
        self.tokenizer = None
        
        # Проверяем, используется ли OpenRouter по умолчанию
        if self._is_openrouter_enabled():
            logger.info("🌐 OpenRouter включён - локальная модель НЕ загружается")
        else:
            logger.info("💡 Локальная модель будет загружена при первом использовании (lazy load)")
        
        # Инициализация кэша
        # Размер кэша определён в config.py (EMBEDDING_CACHE_SIZE)
        self.embedding_cache = EmbeddingCache(max_size=EMBEDDING_CACHE_SIZE)

    def _init_embedding_model(self):
        """
        Загрузка модели эмбеддингов (Qwen) в память.
        
        Использует библиотеку `transformers`. Модель загружается в режиме `eval` (inference only).
        Если доступна CUDA, используется FP16 для экономии видеопамяти и ускорения.
        
        ВАЖНО: Эта функция вызывается лениво (lazy load) - только при первом
        обращении к локальной модели, если OpenRouter отключён.
        """
        if self._embedding_model_loaded:
            return  # Уже загружена
            
        logger.info(f"📥 Загрузка локальной модели эмбеддингов: {QWEN_MODEL_PATH}")
        logger.info("⏳ Это может занять некоторое время...")
        
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
            
        self._embedding_model_loaded = True
        logger.info("✅ Локальная модель эмбеддингов загружена")

    def _ensure_embedding_model_loaded(self):
        """
        Гарантирует, что локальная модель эмбеддингов загружена.
        
        Вызывается перед использованием локальной модели.
        Если модель ещё не загружена - загружает её (lazy load).
        """
        if not self._embedding_model_loaded:
            self._init_embedding_model()

    def get_embeddings_batch(self, texts: List[str], batch_size: int = 8) -> np.ndarray:
        """
        Генерация эмбеддингов для списка текстов (Batch Inference).

        Автоматически выбирает провайдер:
        - OpenRouter API: если включён и настроен
        - Локальная модель: GPU batch inference
        
        Args:
            texts (List[str]): Список исходных текстов.
            batch_size (int): Размер пакета (default: 8).
            
        Returns:
            np.ndarray: Массив векторов размерности (N, D), где N - кол-во текстов, D - размерность модели.
        """
        # Выбор провайдера на основе настроек
        if self._is_openrouter_enabled():
            return self._get_embeddings_batch_openrouter(texts, batch_size)
        else:
            return self._get_embeddings_batch_local(texts, batch_size)

    def _get_embeddings_batch_openrouter(self, texts: List[str], batch_size: int = 8) -> np.ndarray:
        """
        Батчевая генерация эмбеддингов через OpenRouter API (параллельно).
        
        Использует ThreadPoolExecutor для ускорения обработки большого количества текстов.
        Размер батча и количество воркеров берутся из конфигурации.
        
        Args:
            texts (List[str]): Список текстов для эмбеддинга
            batch_size (int): Игнорируется для API (используется API_EMBEDDING_BATCH_SIZE)
            
        Returns:
            np.ndarray: Массив эмбеддингов (N, D)
        """
        # Используем настройки из конфига для максимальной скорости
        batch_size = API_EMBEDDING_BATCH_SIZE
        max_workers = API_MAX_WORKERS
        
        # Получаем настройки OpenRouter
        or_settings = self._get_openrouter_settings()
        api_key = or_settings["api_key"]
        model = or_settings["model"]
        
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenRouter API ключ не настроен")
        
        # Разбиваем на батчи
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        total_batches = len(batches)
        
        logger.info(
            f"🌐 OpenRouter Parallel: {len(texts)} текстов → {total_batches} батчей "
            f"(по {batch_size}), {max_workers} потоков"
        )
        
        # Функция для обработки одного батча (выполняется в потоке)
        def process_batch(batch_texts, batch_idx):
            # Нормализация и проверка на пустые строки
            processed_texts = []
            for i, t in enumerate(batch_texts):
                clean_t = t.strip()
                if not clean_t:
                    logger.warning(f"⚠️ Warning: Пустая строка в батче {batch_idx}, индекс {i}. Заменяем на placeholders.")
                    processed_texts.append("пусто")
                else:
                    processed_texts.append(clean_t.lower())
            
            batch_texts = processed_texts

            try:
                # ВАЖНО: Создаем свой клиент для каждого потока (хотя httpx.Client потокобезопасен, 
                # context manager лучше использовать локально)
                with httpx.Client(timeout=120.0) as client:
                    response = client.post(
                        "https://openrouter.ai/api/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://ksr-matcher.local",
                            "X-Title": "KSR Matcher"
                        },
                        json={
                            "model": model,
                            "input": batch_texts,
                            "encoding_format": "float"
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        embeddings = []
                        if "data" in data and isinstance(data["data"], list):
                            # Сортируем по index для гарантии порядка внутри батча
                            sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
                            for item in sorted_data:
                                emb = item.get("embedding", [])
                                if emb:
                                    emb_np = np.array(emb, dtype=np.float32)
                                    # L2 нормализация
                                    norm = np.linalg.norm(emb_np)
                                    if norm > 0:
                                        emb_np = emb_np / norm
                                    embeddings.append(emb_np)
                            return embeddings
                        else:
                            # ЛОГИРУЕМ ПРОБЛЕМНЫЙ БАТЧ
                            logger.error(f"❌ OpenRouter Invalid Response: {data}")
                            logger.error(f"🔍 Problematic Batch Content (first 5): {batch_texts[:5]}")
                            raise HTTPException(status_code=500, detail=f"Неожиданный формат ответа OpenRouter: {str(data)[:500]}")
                    elif response.status_code == 401:
                        raise HTTPException(status_code=401, detail="Неверный OpenRouter API ключ")
                    elif response.status_code == 429:
                        logger.warning(f"⚠️ Rate limit на батче {batch_idx}. Пауза 2с...")
                        time.sleep(2)
                        # Простейшая ретрай логика (можно улучшить)
                        raise HTTPException(status_code=429, detail="OpenRouter Rate Limit")
                    else:
                        error_text = response.text[:200] if response.text else "Неизвестная ошибка"
                        raise HTTPException(status_code=500, detail=f"Ошибка OpenRouter ({response.status_code}): {error_text}")
                        
            except Exception as e:
                logger.error(f"❌ Ошибка OpenRouter batch {batch_idx}: {e}")
                raise e

        # Запускаем параллельное выполнение
        # Используем future для сохранения порядка результатов
        from concurrent.futures import as_completed
        
        results_map = {} # {index: embeddings}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(process_batch, batch, i): i 
                for i, batch in enumerate(batches)
            }
            
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    batch_embeddings = future.result()
                    results_map[idx] = batch_embeddings
                    
                    # Логируем прогресс каждые 5 батчей
                    if (idx + 1) % 5 == 0 or (idx + 1) == total_batches:
                        logger.info(f"✅ OpenRouter: готово батчей {len(results_map)}/{total_batches}")
                        
                except Exception as e:
                    # Если один батч упал - падаем целиком (для целостности данных)
                    logger.error(f"💥 Критическая ошибка в батче {idx}, остановка.")
                    raise e
        
        # Собираем итоговый массив в правильном порядке
        all_embeddings = []
        for i in range(len(batches)):
             all_embeddings.extend(results_map[i])
             
        if not all_embeddings:
            return np.array([])
            
        return np.vstack(all_embeddings)

    def _get_embeddings_batch_local(self, texts: List[str], batch_size: int = 8) -> np.ndarray:
        """
        Батчевая генерация эмбеддингов через локальную модель (GPU).
        
        Оптимизирована для GPU: обрабатывает данные пакетами (batch_size),
        чтобы эффективно использовать параллелизм CUDA ядер.
        
        Args:
            texts (List[str]): Список исходных текстов.
            batch_size (int): Размер пакета (default: 8).
            
        Returns:
            np.ndarray: Массив векторов размерности (N, D).
        """
        # Гарантируем загрузку локальной модели (lazy load)
        self._ensure_embedding_model_loaded()
        
        all_embeddings = []
        
        logger.debug(f"🖥️ Локальная модель: генерация {len(texts)} эмбеддингов")
        
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
                raise e
                
        if not all_embeddings:
            return np.array([])
            
        return np.vstack(all_embeddings)

    def save_configuration(self):
        """
        Сохранение текущей конфигурации в JSON файл.
        Вызывается после любых изменений в настройках или списке баз.
        
        Поддерживает секцию _settings для глобальных настроек (статусы и др.)
        """
        try:
            config = {}
            for name, meta in self.collections_metadata.items():
                # Специальная обработка секции _settings
                if name == "_settings":
                    config["_settings"] = meta
                    continue
                    
                config[name] = {
                    "description": meta.get("description", f"База {name}"),
                    "columns": meta.get("columns", {"code": "code", "description": "description"}),
                    "thresholds": meta.get("thresholds", {"cosine": 0.45, "rerank": 0.6}),
                    "last_updated": meta.get("last_updated", ""),
                    "visible": meta.get("visible", True),
                    "locked": meta.get("locked", False)
                }
            
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info("💾 Конфигурация успешно сохранена")
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения конфигурации: {e}")

    def _is_openrouter_enabled(self) -> bool:
        """
        Проверяет, включён ли OpenRouter для генерации эмбеддингов.
        
        Returns:
            True если OpenRouter включён и настроен, False иначе
        """
        settings = self.collections_metadata.get("_settings", {})
        openrouter = settings.get("openrouter", {})
        return openrouter.get("enabled", False) and bool(openrouter.get("api_key", ""))

    def _get_openrouter_settings(self) -> dict:
        """
        Получает настройки OpenRouter.
        
        Returns:
            dict с ключами: api_key, model
        """
        settings = self.collections_metadata.get("_settings", {})
        openrouter = settings.get("openrouter", {})
        return {
            "api_key": openrouter.get("api_key", ""),
            "model": openrouter.get("model", "qwen/qwen3-embedding-4b")
        }

    def _get_embedding_openrouter_sync(self, text: str) -> np.ndarray:
        """
        Синхронное получение эмбеддинга через OpenRouter API.
        
        Использует httpx для синхронного HTTP запроса к API.
        
        Args:
            text: Текст для генерации эмбеддинга
            
        Returns:
            np.ndarray: Вектор эмбеддинга
            
        Raises:
            HTTPException: При ошибке API запроса
        """
        try:
            # Нормализуем текст (lowercase + strip)
            normalized_text = text.lower().strip()
            
            # Получаем настройки OpenRouter
            or_settings = self._get_openrouter_settings()
            api_key = or_settings["api_key"]
            model = or_settings["model"]
            
            if not api_key:
                raise HTTPException(status_code=500, detail="OpenRouter API ключ не настроен")
            
            # Выполняем синхронный HTTP запрос к OpenRouter API
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    "https://openrouter.ai/api/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://ksr-matcher.local",
                        "X-Title": "KSR Matcher"
                    },
                    json={
                        "model": model,
                        "input": normalized_text,
                        "encoding_format": "float"
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data and len(data["data"]) > 0:
                        embedding = data["data"][0].get("embedding", [])
                        if embedding:
                            # Конвертируем в numpy array и нормализуем
                            embedding_np = np.array(embedding, dtype=np.float32)
                            # L2 нормализация
                            norm = np.linalg.norm(embedding_np)
                            if norm > 0:
                                embedding_np = embedding_np / norm
                            return embedding_np
                        else:
                            raise HTTPException(status_code=500, detail="OpenRouter вернул пустой эмбеддинг")
                    else:
                        raise HTTPException(status_code=500, detail="Неожиданный формат ответа OpenRouter")
                elif response.status_code == 401:
                    raise HTTPException(status_code=401, detail="Неверный OpenRouter API ключ")
                elif response.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"Модель '{model}' не найдена в OpenRouter")
                else:
                    error_text = response.text[:200] if response.text else "Неизвестная ошибка"
                    raise HTTPException(status_code=500, detail=f"Ошибка OpenRouter API ({response.status_code}): {error_text}")
                    
        except HTTPException:
            raise
        except httpx.TimeoutException:
            logger.error("⏱️ Таймаут запроса к OpenRouter API")
            raise HTTPException(status_code=504, detail="Таймаут запроса к OpenRouter API")
        except httpx.ConnectError:
            logger.error("🔌 Не удалось подключиться к OpenRouter API")
            raise HTTPException(status_code=503, detail="Не удалось подключиться к OpenRouter API")
        except Exception as e:
            logger.error(f"❌ Ошибка OpenRouter эмбеддинга: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка OpenRouter: {str(e)}")

    def _get_embedding_local_sync(self, text: str) -> np.ndarray:
        """
        Синхронное получение эмбеддинга через локальную модель Qwen.
        
        Args:
            text: Текст для генерации эмбеддинга
            
        Returns:
            np.ndarray: Вектор эмбеддинга
        """
        # Гарантируем загрузку локальной модели (lazy load)
        self._ensure_embedding_model_loaded()
        
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
            logger.error(f"Ошибка локальной генерации эмбеддинга: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга: {str(e)}")

    def _get_embedding_sync(self, text: str) -> np.ndarray:
        """
        Синхронное получение эмбеддинга с автоматическим выбором провайдера.
        
        Если OpenRouter включён и настроен - использует API,
        иначе использует локальную модель Qwen.
        
        Args:
            text: Текст для генерации эмбеддинга
            
        Returns:
            np.ndarray: Вектор эмбеддинга
        """
        if self._is_openrouter_enabled():
            logger.debug("🌐 Использую OpenRouter для генерации эмбеддинга")
            return self._get_embedding_openrouter_sync(text)
        else:
            logger.debug("🖥️ Использую локальную модель для генерации эмбеддинга")
            return self._get_embedding_local_sync(text)

    def get_embedding_dimension(self) -> int:
        """
        Возвращает размерность эмбеддингов текущего провайдера.
        
        Автоматически определяет какой провайдер используется:
        - OpenRouter API: размерность зависит от модели (обычно 768-4096)
        - Локальная модель Qwen: 1024
        
        Returns:
            int: Размерность вектора эмбеддинга
        """
        if self._is_openrouter_enabled():
            # Для OpenRouter определяем размерность по модели
            # Известные размерности популярных моделей:
            or_settings = self._get_openrouter_settings()
            model = or_settings.get("model", "")
            
            # Размерности известных моделей OpenRouter
            known_dimensions = {
                "thenlper/gte-large": 1024,
                "text-embedding-3-small": 1536,
                "text-embedding-3-large": 3072,
                "text-embedding-ada-002": 1536,
                "voyage-large-2": 1536,
                "voyage-code-2": 1536,
                # Qwen и подобные модели обычно используют 2560
            }
            
            # Проверяем известные модели
            for known_model, dim in known_dimensions.items():
                if known_model in model.lower():
                    logger.info(f"📐 Размерность модели {model}: {dim}")
                    return dim
            
            # Для неизвестных моделей пробуем сгенерировать тестовый эмбеддинг
            try:
                logger.info(f"📐 Определение размерности для модели {model}...")
                test_embedding = self._get_embedding_openrouter_sync("тест")
                dim = len(test_embedding)
                logger.info(f"📐 Размерность модели {model}: {dim}")
                return dim
            except Exception as e:
                logger.error(f"❌ Не удалось определить размерность: {e}")
                # Возвращаем типичную размерность для Qwen-подобных моделей
                return 2560
        else:
            # Локальная модель - получаем размерность из config
            self._ensure_embedding_model_loaded()
            if self.embedding_model is not None:
                try:
                    dim = self.embedding_model.config.hidden_size
                    logger.info(f"📐 Размерность локальной модели: {dim}")
                    return dim
                except AttributeError:
                    pass
            # Fallback для Qwen-подобных моделей
            return 1024

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

    # === BM25 METHODS ===

    def _ensure_bm25_index(self, collection_name: str):
        """
        Гарантирует, что для коллекции построен индекс BM25.
        Если индекса нет - строит его с нуля (загружает все данные).
        """
        if collection_name in self.bm25_indices:
            return

        logger.info(f"⏳ Building BM25 index for '{collection_name}'...")
        start = time.time()
        
        # Загружаем все документы (code -> full_description)
        # Используем full_description, так как это наиболее точное название материала
        # Если full_description нет, используем description
        
        records = self.get_all_records(collection_name)
        if not records:
             logger.warning(f"⚠️ Collection '{collection_name}' is empty, skipping BM25 build.")
             return

        # Подготовка корпуса для BM25
        # Нам нужно {id: text}. В качестве ID используем UUID записи или code.
        # get_all_records возвращает {code: description}.
        # Но нам нужны ID для последующего merge с Qdrant results (которые возвращают ID).
        # Однако, search_vectors возвращает ID точки.
        # Проблема: get_all_records возвращает code, а не uuid point_id.
        # Решение: Давайте модифицируем get_all_records или напишем свой fetcher здесь.
        
        # Переписываем fetch логику для получения map {point_id: text}
        corpus = {}
        offset = None
        columns = self.collections_metadata[collection_name]["columns"]
        
        while True:
            points, next_offset = self.client.scroll(
                collection_name=collection_name,
                limit=2000,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            
            for p in points:
                # Текст для поиска: full_description (короткое имя) приоритетнее
                full_desc = p.payload.get("full_description")
                desc = p.payload.get(columns["description"], "")
                
                # Индексируем текст: "Код + Название" для максимального охвата
                # Добавляем код, чтобы можно было искать по нему
                code = p.payload.get(columns["code"], "")
                
                search_text = f"{code} {full_desc if full_desc else desc}"
                corpus[p.id] = search_text
                
            if next_offset is None:
                break
            offset = next_offset
            
        # Строим индекс
        bm25 = BM25Index()
        bm25.fit(corpus)
        self.bm25_indices[collection_name] = bm25
        
        elapsed = time.time() - start
        logger.info(f"✅ BM25 index for '{collection_name}' built in {elapsed:.2f}s ({len(corpus)} docs)")

    def search_bm25(self, query: str, collection_name: str, top_k: int = 500) -> List[Dict]:
        """
        Выполняет поиск по BM25 индексу.
        
        Returns:
            List[Dict]: [{'id': uuid, 'score': val, ...}] (формат совместим с search_vectors)
        """
        self._ensure_bm25_index(collection_name)
        
        if collection_name not in self.bm25_indices:
             return []
             
        # Поиск
        results = self.bm25_indices[collection_name].search(query, top_k)
        
        # Нам нужно вернуть объекты, похожие на результат search_vectors
        # Но у нас есть только ID и Score.
        # Метаданные (payload) мы не храним в BM25Index для экономии памяти.
        # Мы их подтянем позже или доверимся тому, что Reranker'у нужен только текст?
        # Нет, Reranker'у нужен текст. И фронтенду нужны данные.
        # Поэтому нам придется подгрузить данные для найденных ID.
        # Это может быть накладно (500 id -> retrieve).
        # ЭВРИСТИКА: BM25 быстрый, но retrieve payload может быть медленным.
        # Однако Qdrant retrieve by ID batch - быстрый.
        
        return results

    def invalidate_bm25(self, collection_name: str):
        """Сбрасывает индекс BM25 для коллекции (вызывать при обновлении данных)."""
        if collection_name in self.bm25_indices:
            del self.bm25_indices[collection_name]
            logger.info(f"🗑️ BM25 index invalidated for '{collection_name}'")

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
            
            # === ВАЖНО: Сначала загружаем секцию _settings (глобальные настройки) ===
            # Она не является коллекцией Qdrant, поэтому обрабатывается отдельно
            if "_settings" in config:
                self.collections_metadata["_settings"] = config["_settings"]
                logger.info("⚙️ Загружены глобальные настройки (_settings)")

            for collection_name, db_config in config.items():
                # Пропускаем секцию _settings - она уже обработана выше
                if collection_name == "_settings":
                    continue
                    
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
            # Исключаем _settings из проверки (она не является коллекцией)
            real_collections = {
                name: meta for name, meta in self.collections_metadata.items()
                if name != "_settings"
            }
            
            if (
                hasattr(self, "current_collection")
                and self.current_collection not in real_collections
            ):
                if real_collections:
                    # Устанавливаем первую найденную коллекцию как активную (исключая _settings)
                    self.current_collection = next(iter(real_collections))
                    logger.warning(
                        f"⚠️ Предыдущая активная коллекция недоступна, "
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
        
        # Вспомогательная функция для парсинга пути и создания условий фильтрации
        def build_path_conditions(path: str) -> List[FieldCondition]:
            """
            Парсит путь категории и создаёт условия фильтрации по всем уровням.
            
            ИСПРАВЛЕНО: Раньше фильтр искал полный путь в одном поле (path_level_N = "Арматура → Краны"),
            но в базе данных каждый уровень хранится отдельно (path_level_1 = "Арматура", path_level_2 = "Краны").
            
            Args:
                path: Полный путь категории, например "Арматура → Краны → Шаровые"
            
            Returns:
                Список FieldCondition для фильтрации по всем уровням пути
            """
            separator = " → "
            parts = [p.strip() for p in path.split(separator) if p.strip()]
            conditions = []
            
            for i, part in enumerate(parts):
                level = i + 1  # Уровни начинаются с 1
                conditions.append(
                    FieldCondition(
                        key=f"path_level_{level}",
                        match=MatchValue(value=part)
                    )
                )
            
            return conditions
        
        # Приоритет: множественный фильтр (filter_paths) > одиночный (filter_path)
        if filter_paths and len(filter_paths) > 0:
            # Множественный фильтр с OR-логикой (should)
            # Формат: [{"path": "Арматура → Краны", "level": 2}, ...]
            # Каждая категория - это набор AND-условий по всем уровням пути
            # Несколько категорий объединяются через OR (should)
            
            if len(filter_paths) == 1:
                # Одна категория - просто must условия по всем уровням
                path = filter_paths[0].get("path")
                if path:
                    conditions = build_path_conditions(path)
                    if conditions:
                        qdrant_filter = Filter(must=conditions)
                        logger.info(f"🔍 Фильтр иерархии (одиночный): {' AND '.join([f'path_level_{i+1}={c.match.value}' for i, c in enumerate(conditions)])}")
            else:
                # Несколько категорий - OR между категориями
                # Каждая категория = Filter(must=[условия по уровням])
                category_filters = []
                for fp in filter_paths:
                    path = fp.get("path")
                    if path:
                        conditions = build_path_conditions(path)
                        if conditions:
                            # Создаём вложенный фильтр для каждой категории
                            category_filters.append(Filter(must=conditions))
                
                if category_filters:
                    # should = OR логика между категориями
                    qdrant_filter = Filter(should=category_filters)
                    paths_str = ", ".join([f"'{fp.get('path')}'" for fp in filter_paths])
                    logger.info(f"🔍 Множественный фильтр иерархии (OR): {paths_str}")
        
        elif filter_path and filter_level:
            # Одиночный фильтр (обратная совместимость)
            # ИСПРАВЛЕНО: Парсим путь и создаём условия по всем уровням
            conditions = build_path_conditions(filter_path)
            if conditions:
                qdrant_filter = Filter(must=conditions)
                logger.info(f"🔍 Фильтр иерархии: {' AND '.join([f'path_level_{i+1}={c.match.value}' for i, c in enumerate(conditions)])}")

        # === ВАЖНО: Исключаем папки из поиска материалов ===
        # Основной поиск /match предназначен ТОЛЬКО для материалов.
        # Папки (is_folder=true) используются только в /hierarchy/{db}/search
        exclude_folders_condition = FieldCondition(
            key="is_folder",
            match=MatchValue(value=True)
        )
        
        if qdrant_filter is None:
            # Фильтра не было - создаём новый только с исключением папок
            qdrant_filter = Filter(must_not=[exclude_folders_condition])
        else:
            # Фильтр уже есть - добавляем must_not к существующему
            existing_must = qdrant_filter.must or []
            existing_must_not = qdrant_filter.must_not or []
            existing_should = qdrant_filter.should or []
            
            # Добавляем исключение папок
            existing_must_not.append(exclude_folders_condition)
            
            qdrant_filter = Filter(
                must=existing_must if existing_must else None,
                must_not=existing_must_not,
                should=existing_should if existing_should else None
            )

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
                limit=1000, # Оптимизация: увеличен батч
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
            # НОВАЯ ЛОГИКА v2: path_level_N содержит только своё название
            path_levels = generate_path_levels(description, separator="→")
            
            payload = {
                columns["code"]: code,
                columns["description"]: description,  # Legacy: сохраняем исходное описание
                **path_levels,  # path_level_N, path_depth, full_description, context_description
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
        Массовое обновление записей с генерацией векторов.
        
        НОВАЯ ЛОГИКА v2: Эмбеддинги генерируются из context_description.
        """
        collection = collection_name or self.current_collection
        if not collection or collection not in self.collections_metadata:
            return 0
            
        if not records:
            return 0
            
        columns = self.collections_metadata[collection]["columns"]
        
        # 1. Сначала вычисляем path_levels для каждой записи
        codes = [r["code"] for r in records]
        descriptions = [r["description"] for r in records]
        
        batch_path_levels = []
        context_texts = []  # Тексты для эмбеддингов (context_description)
        
        for desc in descriptions:
            # Генерируем поля path_level_N
            path_levels = generate_path_levels(desc, separator="→")
            batch_path_levels.append(path_levels)
            # Используем context_description для эмбеддингов
            context_texts.append(path_levels.get("context_description", desc))
        
        # 2. Генерация векторов (батчевая) из context_description
        embeddings = self.get_embeddings_batch(context_texts, batch_size=8)
        
        # 3. Подготовка точек для Qdrant
        points = []
        timestamp = time.time()
        
        for code, desc, emb, path_levels in zip(codes, descriptions, embeddings, batch_path_levels):
            # Генерируем ID (UUID5 от кода) для детерминизма
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, code))
            
            # path_levels уже содержит:
            # - path_level_N (отдельные уровни категорий)
            # - path_depth, full_description, context_description
            
            payload = {
                columns["code"]: code,
                columns["description"]: desc,  # Legacy: сохраняем исходное описание
                **path_levels,  # path_level_N, path_depth, full_description, context_description
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
             # Инвалидируем BM25
             self.invalidate_bm25(collection)
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
        
        # Инвалидируем BM25
        self.invalidate_bm25(collection)
        
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

    def close(self):
        """
        Корректное закрытие всех ресурсов менеджера.
        
        Вызывается при завершении работы приложения для предотвращения
        ошибок с portalocker при shutdown Python-интерпретатора.
        """
        try:
            # Закрываем Qdrant клиент
            if self.client:
                self.client.close()
                logger.info("✅ Qdrant клиент корректно закрыт")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при закрытии Qdrant: {e}")
        
        # Останавливаем пул потоков
        try:
            self.executor.shutdown(wait=False)
            logger.info("✅ ThreadPoolExecutor остановлен")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при остановке executor: {e}")


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


# === ОБРАБОТЧИК ЗАВЕРШЕНИЯ ПРИЛОЖЕНИЯ ===
@app.on_event("shutdown")
async def shutdown_event():
    """
    Обработчик события завершения FastAPI приложения.
    
    Корректно закрывает Qdrant клиент до завершения Python-интерпретатора,
    чтобы избежать ошибок с portalocker при shutdown.
    """
    logger.info("🛑 Завершение работы сервера...")
    db_manager.close()
    logger.info("👋 Сервер остановлен корректно")


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
    """
    Запрос на обновление одной ячейки.
    
    Поддерживаемые поля:
    - code: код записи
    - description: полное описание (legacy)
    - full_description: описание материала
    - path_level_N: уровни категорий
    - status: статус записи (active, draft, deprecated и др.)
    """
    code: str = None  # Теперь опциональный
    field: str  # Имя поля для обновления
    value: str  # Новое значение


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
    """
    Результат поиска - один кандидат.
    
    Attributes:
        rank: Позиция в выдаче (1 = лучший)
        code: Код материала (КСР)
        description: Полное описание (для обратной совместимости, может содержать путь категорий)
        material_name: Название материала БЕЗ категорий (из full_description)
        category_path: Путь категорий (например, "Арматура → Краны → Шаровые")
        reranker_score: Оценка релевантности от reranker
        cosine_similarity: Косинусное сходство с запросом
    """

    rank: int
    code: str
    description: str
    material_name: Optional[str] = None  # Название материала без категорий
    category_path: Optional[str] = None  # Путь категорий для навигации в каталоге
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

    async def cancel_job(self, job_id: str) -> bool:
        """Отменяет выполнение задачи"""
        job = self.jobs.get(job_id)
        if job and job.status in ["pending", "processing"]:
            job.status = "cancelled"
            job.details = job.details + " [Остановлено пользователем]" if job.details else "[Остановлено пользователем]"
            logger.info(f"🛑 Job {job_id} cancelled by user")
            return True
        return False

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
                    if job.status != "error" and job.status != "cancelled":
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
        
        Поддерживает два режима генерации path_level_N:
        1. Из description (по умолчанию) - если hierarchy не указан
        2. Из отдельного поля hierarchy - если указано в записях
        
        НОВАЯ ЛОГИКА v3: Автоматическое создание записей для папок (категорий).
        После импорта материалов извлекаются уникальные папки и индексируются
        с флагом is_folder=true и полем leaf_name для rerank.
        
        data: {
            "collection_name": str,
            "records": List[dict], # [{"code": "...", "description": "...", "hierarchy": "..." (опционально)}]
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
        
        # Получаем размерность текущей модели эмбеддингов (API или локальная)
        model_dim = db_manager.get_embedding_dimension()
        
        # Проверяем размерность
        if collection_dim and model_dim and collection_dim != model_dim:
            raise ValueError(
                f"Размерность коллекции ({collection_dim}) не совпадает с размерностью текущей модели ({model_dim}). "
                f"Удалите коллекцию '{collection_name}' и создайте заново с правильной размерностью."
            )
             
        # Определяем размер батча для обработки
        # Если используется OpenRouter - увеличиваем батч для параллельной загрузки
        if db_manager._is_openrouter_enabled():
             # Используем полную мощность: размер батча API * количество воркеров
             BATCH_SIZE = API_EMBEDDING_BATCH_SIZE * API_MAX_WORKERS
             logger.info(f"🚀 Включен параллельный импорт: батч {BATCH_SIZE} (API)")
        else:
             # Локальный режим (GPU) - используем стандартный батч
             BATCH_SIZE = 32
             logger.info(f"🐢 Включен локальный импорт: батч {BATCH_SIZE} (GPU)")
        processed = 0
        
        # === НАКОПЛЕНИЕ path_levels ДЛЯ ИЗВЛЕЧЕНИЯ ПАПОК ===
        # Собираем все path_levels для последующего извлечения уникальных папок
        all_path_levels_for_folders = []
        
        # Итерируемся батчами
        for i in range(0, total, BATCH_SIZE):
            # Проверка отмены задачи
            if job.status == "cancelled":
                logger.warning(f"🛑 Import job {job.id} stopped by user")
                # Обновляем детали, если ещё не обновлены
                if "[Остановлено пользователем]" not in job.details:
                     job.details += " [Остановлено пользователем]"
                return

            batch = records[i : i + BATCH_SIZE]
            
            # Подготовка данных
            codes = [r["code"] for r in batch]
            descriptions = [r["description"] for r in batch]
            metas = [r.get("meta", {}) for r in batch]
            # Получаем иерархию (если указана, иначе None - будет использоваться description)
            hierarchies = [r.get("hierarchy") for r in batch]
            
            # === НОВАЯ ЛОГИКА v2: Сначала вычисляем path_levels ===
            # Эмбеддинги должны генерироваться из context_description
            batch_path_levels = []
            context_texts = []  # Тексты для эмбеддингов (context_description)
            
            for desc, hierarchy in zip(descriptions, hierarchies):
                # === НОВОЕ: Применяем правила очистки ===
                desc = apply_cleaning_rules(desc, "description")
                if hierarchy:
                    hierarchy = apply_cleaning_rules(hierarchy, "hierarchy")
                
                # Генерируем поля path_level_N
                if hierarchy and hierarchy != desc:
                    # Комбинированный режим: иерархия (папки) + описание (материал)
                    path_levels = generate_path_levels_combined(hierarchy, desc, separator="→")
                else:
                    # Стандартный режим: всё из описания
                    path_levels = generate_path_levels(desc, separator="→")
                
                # === ДОПОЛНИТЕЛЬНАЯ ОЧИСТКА УРОВНЕЙ ===
                # Правила очистки (regex ^...) работают только для начала строки.
                # Вложенные уровни ("Группа 2") не чистятся, так как они в середине.
                # Поэтому проходим по каждому уровню и чистим отдельно.
                for key, value in path_levels.items():
                    if key.startswith("path_level_") and isinstance(value, str):
                        cleaned_value = apply_cleaning_rules(value, "hierarchy")
                        path_levels[key] = cleaned_value.strip()

                batch_path_levels.append(path_levels)
                # Используем context_description для эмбеддингов
                context_texts.append(path_levels.get("context_description", desc))

            
            # Накапливаем path_levels для извлечения папок
            all_path_levels_for_folders.extend(batch_path_levels)
            
            # === CRITICAL: GPU LOCK ===
            # Защищаем вызов тяжелой модели
            # Теперь эмбеддинги генерируются из context_description!
            async with db_manager.gpu_lock:
                 embeddings = await asyncio.get_event_loop().run_in_executor(
                     db_manager.executor,
                     lambda: db_manager.get_embeddings_batch(context_texts, batch_size=BATCH_SIZE)
                 )
            
            # Формирование точек
            points = []
            timestamp = time.time()
            columns = db_manager.collections_metadata.get(collection_name, {}).get("columns", {"code": "code", "description": "description"})
            
            for code, desc, emb, meta, path_levels in zip(codes, descriptions, embeddings, metas, batch_path_levels):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(code)))
                
                # path_levels уже содержит:
                # - path_level_1, path_level_2, ... (отдельные уровни категорий)
                # - path_depth (количество уровней категорий)
                # - full_description (полное описание материала)
                # - context_description (контекст для эмбеддингов)
                
                # === НОВОЕ: Вычисляем folder_ids для связи материал → папки ===
                # Это позволяет при редактировании материала сразу знать связанные папки
                folder_ids = []
                path_depth = path_levels.get("path_depth", 0)
                if path_depth > 0:
                    # Собираем путь из path_level_N
                    parts = []
                    for lvl in range(1, path_depth + 1):
                        part = path_levels.get(f"path_level_{lvl}", "")
                        if part:
                            parts.append(part)
                            # Вычисляем ID папки для каждого уровня
                            folder_full_path = " → ".join(parts)
                            folder_code_str = f"folder::{folder_full_path.replace(' → ', '::')}"
                            folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code_str))
                            folder_ids.append(folder_id)
                
                # Получаем настройки статусов для default_status
                settings = db_manager.collections_metadata.get("_settings", {})
                default_status = settings.get("default_status", "active")
                
                # ISO timestamp для updated_at
                # ISO timestamp для updated_at
                iso_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                
                payload = {
                    columns["code"]: code,
                    columns["description"]: desc,  # Legacy: сохраняем исходное описание
                    **path_levels,  # path_level_N, path_depth, full_description, context_description
                    "folder_ids": folder_ids,  # Массив ID всех папок в иерархии
                    "timestamp": timestamp,
                    "source": "import_job",
                    "is_folder": False,  # Материал, не папка
                    # === НОВЫЕ ПОЛЯ v3: версионирование и статусы ===
                    "updated_at": iso_timestamp,  # Дата создания/обновления
                    "version": 1,                 # Начальная версия
                    "status": default_status,     # Статус по умолчанию
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
            # Прогресс материалов: 0-80%
            job.progress = int((processed / total) * 80)
            
            # Обновляем счетчик
            if collection_name in db_manager.collections_metadata:
                 db_manager.collections_metadata[collection_name]["record_count"] = processed # Примерно, точнее будет после всего
            
            # Даем передышку event loop
            await asyncio.sleep(0.01)
        
        # === ЭТАП 2: ИНДЕКСАЦИЯ ПАПОК (КАТЕГОРИЙ) ===
        # Извлекаем уникальные папки из накопленных path_levels
        logger.info(f"📁 Начинаем извлечение и индексацию папок для коллекции '{collection_name}'...")
        job.details = "Извлечение папок из иерархии..."
        
        folders = extract_folders_from_records(all_path_levels_for_folders, separator="→")
        
        if folders:
            logger.info(f"📁 Найдено {len(folders)} уникальных папок для индексации")
            job.details = f"Индексация {len(folders)} папок..."
            
            # Генерируем эмбеддинги для папок батчами
            if db_manager._is_openrouter_enabled():
                FOLDER_BATCH_SIZE = API_EMBEDDING_BATCH_SIZE * API_MAX_WORKERS
                logger.info(f"🚀 Включен параллельный индекс папок: батч {FOLDER_BATCH_SIZE} (API)")
            else:
                FOLDER_BATCH_SIZE = 32
                logger.info(f"🐢 Включен локальный индекс папок: батч {FOLDER_BATCH_SIZE} (GPU)")
            folder_points = []
            timestamp = time.time()
            columns = db_manager.collections_metadata.get(collection_name, {}).get("columns", {"code": "code", "description": "description"})
            
            for i in range(0, len(folders), FOLDER_BATCH_SIZE):
                folder_batch = folders[i : i + FOLDER_BATCH_SIZE]
                
                # Тексты для генерации эмбеддингов - full_path папок
                folder_texts = [f["full_path"] for f in folder_batch]
                
                # Генерация эмбеддингов для папок
                async with db_manager.gpu_lock:
                    folder_embeddings = await asyncio.get_event_loop().run_in_executor(
                        db_manager.executor,
                        lambda texts=folder_texts: db_manager.get_embeddings_batch(texts, batch_size=FOLDER_BATCH_SIZE)
                    )
                
                # Формирование точек для папок
                for folder, emb in zip(folder_batch, folder_embeddings):
                    # Уникальный ID папки: folder::{full_path}
                    folder_code = f"folder::{folder['full_path'].replace(' → ', '::')}"
                    folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
                    
                    # Payload папки с ключевыми полями для поиска
                    payload = {
                        columns["code"]: folder_code,
                        columns["description"]: folder["full_path"],  # full_path для совместимости
                        "full_path": folder["full_path"],              # Полный путь (контекст)
                        "leaf_name": folder["leaf_name"],              # Название папки (для rerank!)
                        "path_depth": folder["level"],                 # Уровень вложенности
                        "items_count": folder["items_count"],          # Количество материалов
                        "is_folder": True,                             # Флаг папки
                        "timestamp": timestamp,
                        "source": "import_job_folders",
                        **folder["path_levels"]  # path_level_1, path_level_2, ...
                    }
                    
                    folder_points.append(PointStruct(
                        id=folder_id,
                        vector=emb.tolist(),
                        payload=payload
                    ))
                
                # Прогресс папок: 80-95%
                folder_progress = 80 + int((min(i + FOLDER_BATCH_SIZE, len(folders)) / len(folders)) * 15)
                job.progress = folder_progress
                
                await asyncio.sleep(0.01)
            
            # Запись папок в Qdrant
            if folder_points:
                db_manager.client.upsert(
                    collection_name=collection_name,
                    points=folder_points
                )
                logger.info(f"✅ Индексировано {len(folder_points)} папок в коллекцию '{collection_name}'")
            
            # === УДАЛЕНИЕ ОСИРОТЕВШИХ ПАПОК ===
            # Папки, которые были в базе, но больше не нужны (нет материалов с таким путём)
            job.details = "Удаление осиротевших папок..."
            
            # Получаем все текущие пути папок из базы
            existing_folder_paths = set()
            scroll_offset = None
            
            folder_filter = Filter(
                must=[
                    FieldCondition(
                        key="is_folder",
                        match=MatchValue(value=True)
                    )
                ]
            )
            
            while True:
                points, scroll_offset = db_manager.client.scroll(
                    collection_name=collection_name,
                    limit=1000,
                    offset=scroll_offset,
                    with_payload=["full_path"],
                    with_vectors=False,
                    scroll_filter=folder_filter
                )
                
                for p in points:
                    full_path = p.payload.get("full_path")
                    if full_path:
                        existing_folder_paths.add(full_path)
                
                if scroll_offset is None:
                    break
            
            # Новые пути папок (из импортируемых данных)
            new_folder_paths = {f["full_path"] for f in folders}
            
            # Осиротевшие папки = существующие - новые
            orphan_paths = existing_folder_paths - new_folder_paths
            
            if orphan_paths:
                # Генерируем ID для удаления
                orphan_ids = []
                for path in orphan_paths:
                    folder_code = f"folder::{path.replace(' → ', '::')}"
                    folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
                    orphan_ids.append(folder_id)
                
                # Удаляем осиротевшие папки
                db_manager.client.delete(
                    collection_name=collection_name,
                    points_selector=orphan_ids
                )
                logger.info(f"🗑️ Удалено {len(orphan_ids)} осиротевших папок")
            else:
                logger.info(f"✅ Осиротевших папок нет")
                
        else:
            logger.info(f"📁 Папки не найдены (записи без иерархии)")
        
        job.progress = 95
        job.details = "Финализация..."
            
        # Финальное обновление счетчика и даты
        info = db_manager.client.get_collection(collection_name)
        if collection_name in db_manager.collections_metadata:
            db_manager.collections_metadata[collection_name]["record_count"] = info.points_count
            db_manager.collections_metadata[collection_name]["last_updated"] = datetime.now().strftime("%d.%m.%Y")
            db_manager.save_configuration()
        
        logger.info(f"✅ Импорт завершён: {processed} материалов + {len(folders) if folders else 0} папок")

# Инициализация менеджера задач (после определения классов)
job_manager = BackgroundJobManager()

# Инициализация сервиса иерархии (кэш навсегда - инвалидация только через API)
hierarchy_service = HierarchyService(cache_ttl=float('inf'))

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
            # Пропускаем служебную секцию настроек
            if name == "_settings":
                continue
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

        # Определяем текущую базу данных (исключаем _settings)
        current_db = db_manager.current_collection
        # Если current_collection не установлена или равна _settings, берём первую видимую
        database_names = [db["name"] for db in databases_list]
        if not current_db or current_db == "_settings" or current_db not in database_names:
            current_db = databases_list[0]["name"] if databases_list else None
        
        return {
            "databases": databases_list,
            "current_database": current_db,
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
        t1 = time.time()
        query_emb = await db_manager.get_embedding_cached(query_text)
        t_embedding = time.time() - t1
        logger.info(f"⏱️ [1] Embedding: {t_embedding:.3f}s")

        # === ШАГ 2: Поиск в Qdrant (теперь асинхронно!) ===
        t2 = time.time()
        candidates = await db_manager.search_similar(
            collection_name=collection_name,
            query_embedding=query_emb,
            top_k=TOP_K_QDRANT,
            score_threshold=COSINE_THRESHOLD,
            filter_path=request.filter_path,
            filter_level=request.filter_level,
            filter_paths=request.filter_paths,
        )
        t_qdrant = time.time() - t2
        logger.info(f"⏱️ [2] Qdrant Search ({len(candidates)} candidates): {t_qdrant:.3f}s")

        # === HYBRID SEARCH: Adding BM25 Results ===
        bm25_candidates_ids = []
        t_bm25 = 0
        t_retrieve = 0
        
        if BM25_ENABLED:
            # BM25 Search
            t3 = time.time()
            try:
                bm25_results = db_manager.search_bm25(query_text, collection_name, top_k=BM25_TOP_K)
                if bm25_results:
                    bm25_candidates_ids = [r['id'] for r in bm25_results]
            except Exception as e:
                logger.error(f"❌ BM25 Error: {e}")
                bm25_results = []
            t_bm25 = time.time() - t3
            logger.info(f"⏱️ [3] BM25 Search ({len(bm25_candidates_ids)} candidates): {t_bm25:.3f}s")

            # === MERGE RESULTS ===
            dense_ids = {c['id'] for c in candidates}
            unique_bm25_ids = [uid for uid in bm25_candidates_ids if uid not in dense_ids]
            
            # Retrieve payloads for BM25-only hits
            if unique_bm25_ids:
                unique_bm25_ids = unique_bm25_ids[:BM25_MAX_RETRIEVE]
                t4 = time.time()
                try:
                    points = db_manager.client.retrieve(
                        collection_name=collection_name,
                        ids=unique_bm25_ids,
                        with_payload=True,
                        with_vectors=False
                    )
                    
                    columns = db_manager.get_columns()
                    bm25_candidates_full = []
                    for hit in points:
                        bm25_candidates_full.append({
                            "id": hit.id,
                            "score": 0.0,
                            "code": hit.payload.get(columns["code"], ""),
                            "description": hit.payload.get(columns["description"], ""),
                            "metadata": hit.payload,
                            "is_bm25_match": True
                        })
                    
                    candidates.extend(bm25_candidates_full)
                    t_retrieve = time.time() - t4
                    logger.info(f"⏱️ [4] BM25 Retrieve ({len(bm25_candidates_full)} payloads): {t_retrieve:.3f}s")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to retrieve BM25 payloads: {e}")

        # === ШАГ 3: Ограничиваем для reranking ===
        # Теперь у нас может быть до 1000 кандидатов (500 dense + 500 sparse).
        # Reranker BGE-M3 тяжелый. Ограничим до 200... А лучше до 300 для гибрида.
        # Но как выбрать лучшие 300 из смешанного списка с разными мериками (cosine vs bm25)?
        # ДУРАЦКИЙ (NO) ПОДХОД: Взять топ-100 Dense + топ-100 BM25.
        # ТЕКУЩИЙ ПОДХОД: Мы просто добавили BM25 в хвост Dense.
        # Если Dense нашел классные вещи, они в начале.
        # Если BM25 нашел уникальные вещи, они в конце.
        # Если мы просто обрежем [:200], мы можем отрезать BM25 результаты!
        
        # ПРАВИЛЬНЫЙ ПОДХОД (Interleaving):
        # Чередовать: 1 dense, 1 bm25, 1 dense, 1 bm25...
        # Пока не наберем MAX_FOR_RERANK.
        
        interleaved_candidates = []
        dense_part = [c for c in candidates if not c.get('is_bm25_match')]
        bm25_part = [c for c in candidates if c.get('is_bm25_match')]
        
        # Сортируем BM25 часть по score (у нас score=0, так что порядок retrieval случаен... А жаль)
        # FIX: В bm25_candidates_full надо было сохранить BM25 score.
        # Но retrieve вернул список в произвольном порядке? Нет, обычно в порядке запроса IDs.
        # Но IDs были отсортированы BM25. Значит порядок сохранен (примерно).
        
        # Параметр из config.py (HYBRID_RERANK_LIMIT)
        
        candidates_for_rerank = []
        if len(candidates) <= HYBRID_RERANK_LIMIT:
            candidates_for_rerank = candidates
        else:
             # Берем 100 лучших Dense (как было раньше)
             candidates_for_rerank.extend(dense_part[:100])
             # И до 30 лучших из BM25 (уникальные ключевые хиты)
             candidates_for_rerank.extend(bm25_part[:30])
             
        logger.info(f"⚖️ Hybrid Rerank Candidates: {len(candidates_for_rerank)} (Dense+BM25)")

        # === ШАГ 4: Reranking ===
        # ИСПРАВЛЕНИЕ: Rerank по full_description (короткое имя материала),
        # а не по description (полный контекстный путь с категориями).
        # запрос пользователя с конкретным названием материала.
        normalized_query = query_text.lower().strip()
        
        # Вспомогательная функция для извлечения описания для реранжирования
        def get_rerank_text(candidate: dict) -> str:
            """
            Извлекает текст для реранжирования, предпочитая full_description.
            
            full_description - короткое название материала (например: "Кран шаровой DN50")
            description - полный контекстный путь (например: "Арматура → Краны → Кран шаровой DN50")
            """
            metadata = candidate.get("metadata", {})
            full_desc = metadata.get("full_description")
            
            if full_desc:
                return full_desc
            else:
                # Fallback для обратной совместимости со старыми записями
                # где нет поля full_description
                if candidate.get("code"):
                    logger.debug(
                        f"⚠️ Запись {candidate['code']} не имеет full_description, "
                        f"используется description для реранжирования"
                    )
                return candidate.get("description", "")
        
        candidate_pairs = [
            (normalized_query, get_rerank_text(c)) for c in candidates_for_rerank
        ]

        t5 = time.time()
        loop = asyncio.get_event_loop()
        rerank_scores = await loop.run_in_executor(
            db_manager.executor, lambda: reranker.predict(candidate_pairs)
        )
        t_rerank = time.time() - t5
        logger.info(f"⏱️ [5] Reranker ({len(candidate_pairs)} pairs): {t_rerank:.3f}s")

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
        # Вспомогательная функция для извлечения material_name и category_path из metadata
        def extract_material_info(result: dict) -> tuple:
            """
            Извлекает название материала и путь категорий из metadata результата.
            
            Args:
                result: Словарь с данными кандидата (включая metadata из Qdrant)
            
            Returns:
                tuple: (material_name, category_path)
                - material_name: Название материала без категорий
                - category_path: Путь категорий через " → " или None
            """
            metadata = result.get("metadata", {})
            
            # 1. Извлекаем название материала
            # Приоритет: full_description > description (fallback для старых данных)
            material_name = metadata.get("full_description")
            if not material_name:
                # Fallback: используем description как есть (старые данные без миграции)
                material_name = result.get("description", "")
            
            # 2. Строим путь категорий из path_level_N полей
            path_depth = metadata.get("path_depth", 0)
            category_parts = []
            
            if path_depth > 0:
                # Собираем все уровни категорий
                for level in range(1, path_depth + 1):
                    level_value = metadata.get(f"path_level_{level}", "")
                    if level_value:
                        category_parts.append(level_value)
            
            # Формируем путь категорий
            category_path = " → ".join(category_parts) if category_parts else None
            
            return material_name, category_path
        
        final_candidates = []
        for idx, r in enumerate(valid_results[:MAX_RESULTS]):
            material_name, category_path = extract_material_info(r)
            final_candidates.append(
                CandidateResult(
                    rank=idx + 1,
                    code=r["code"],
                    description=r["description"],  # Оставляем для обратной совместимости
                    material_name=material_name,
                    category_path=category_path,
                    reranker_score=r["rerank_score"],
                    cosine_similarity=r["score"],
                )
            )

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
    Семантический поиск по каталогу категорий (папок).
    
    ЛОГИКА "Contextual Path with Leaf Focus":
    1. Векторный поиск ТОЛЬКО по папкам (is_folder=true)
    2. Эмбеддинги папок построены по full_path (контекст)
    3. Rerank по leaf_name (название папки) - КЛЮЧЕВОЕ!
    
    ВАЖНО: Поиск ведётся ТОЛЬКО по папкам. Материалы НЕ участвуют в поиске каталога.
    Если папок нет - возвращается пустой результат.
    
    Это позволяет находить папки по короткому запросу (например, "Задвижки"),
    даже если полный путь длинный ("Трубопроводная арматура → Задвижки").
    
    Args:
        database_name: Имя коллекции в Qdrant.
        request: HierarchySearchRequest с текстом запроса.
    
    Returns:
        {
            "categories": [
                {
                    "path": "Арматура → Задвижки",
                    "level": 2,
                    "name": "Задвижки",
                    "items_count": 150,
                    "cosine_score": 0.65,
                    "rerank_score": 0.92
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
        # Для папок используем более низкий порог cosine (папки имеют более короткие тексты)
        cosine_threshold = thresholds.get("cosine", 0.3) * 0.7  # 30% снижение порога для папок
        
        # === ШАГ 1: Генерация эмбеддинга запроса ===
        query_embedding = await db_manager.get_embedding_cached(query_text)
        
        # === ШАГ 2: Поиск ТОЛЬКО по папкам (is_folder=true) ===
        original_collection = db_manager.current_collection
        db_manager.set_active_collection(database_name)
        
        # Формируем фильтр для поиска ТОЛЬКО папок (материалы исключены)
        folder_filter = Filter(
            must=[
                FieldCondition(
                    key="is_folder",
                    match=MatchValue(value=True)
                )
            ]
        )
        
        # Поиск папок в Qdrant
        loop = asyncio.get_event_loop()
        
        def _search_folders():
            return db_manager.client.query_points(
                collection_name=database_name,
                query=query_embedding,
                limit=50,  # Топ-50 папок для rerank
                with_payload=True,
                score_threshold=cosine_threshold,
                query_filter=folder_filter
            ).points
        
        folder_candidates = await loop.run_in_executor(db_manager.executor, _search_folders)
        
        # Восстанавливаем коллекцию
        if original_collection:
            db_manager.set_active_collection(original_collection)
        
        # === ШАГ 3: Обработка результатов ===
        # Если папок нет - возвращаем пустой результат (без fallback на материалы!)
        if not folder_candidates:
            logger.info(f"📁 Папки не найдены для запроса '{query_text[:30]}...'")
            return {
                "categories": [],
                "query": query_text,
                "total_found": 0
            }
        
        logger.info(f"📁 Найдено {len(folder_candidates)} папок для запроса '{query_text[:30]}...'")
        
        # Подготовка кандидатов для rerank
        candidates_for_rerank = []
        for hit in folder_candidates:
            payload = hit.payload
            candidates_for_rerank.append({
                "path": payload.get("full_path", payload.get("description", "")),
                "level": payload.get("path_depth", 0),
                "name": payload.get("leaf_name", ""),  # КЛЮЧЕВОЕ: leaf_name для rerank
                "items_count": payload.get("items_count", 0),
                "cosine_score": round(hit.score, 4),
                "metadata": payload
            })
        
        # === ШАГ 4: Rerank по leaf_name (НЕ по full_path!) ===
        if reranker and len(candidates_for_rerank) > 0:
            normalized_query = query_text.lower().strip()
            
            # КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: rerank по leaf_name (название папки)
            rerank_pairs = [
                (normalized_query, cat["name"].lower()) for cat in candidates_for_rerank
            ]
            
            rerank_scores = await loop.run_in_executor(
                db_manager.executor, lambda: reranker.predict(rerank_pairs)
            )
            
            # Добавляем rerank score
            for i, cat in enumerate(candidates_for_rerank):
                cat["rerank_score"] = round(float(rerank_scores[i]), 4)
            
            # Сортируем по rerank score (ГЛАВНЫЙ критерий для папок)
            candidates_for_rerank.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        else:
            # Если reranker недоступен, сортируем по cosine
            candidates_for_rerank.sort(key=lambda x: x.get("cosine_score", 0), reverse=True)
        
        # Берём топ результатов
        final_categories = candidates_for_rerank[:request.top_k]
        
        # Удаляем metadata из ответа (он был нужен только для обработки)
        for cat in final_categories:
            cat.pop("metadata", None)
        
        logger.info(
            f"🔍 Поиск категорий: '{query_text[:30]}...' | "
            f"Найдено: {len(final_categories)} папок"
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


class AuthResponse(BaseModel):
    """Ответ аутентификации с JWT токеном"""
    status: str
    token: str
    expires_in: int  # Время жизни токена в секундах


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Создаёт JWT токен с заданными данными и сроком действия.
    
    Args:
        data: Данные для включения в токен (payload).
        expires_delta: Время жизни токена (по умолчанию из конфига).
    
    Returns:
        str: Закодированный JWT токен.
    """
    to_encode = data.copy()
    
    # Устанавливаем время истечения (используем timezone-aware datetime)
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    
    to_encode.update({
        "exp": expire,  # Время истечения
        "iat": datetime.now(timezone.utc),  # Время создания
        "type": "admin_access"  # Тип токена
    })
    
    # Кодируем токен
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Проверяет пароль против bcrypt хеша.
    
    Args:
        plain_password: Пароль в открытом виде.
        hashed_password: Хеш пароля из конфигурации.
    
    Returns:
        bool: True если пароль верный.
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Ошибка верификации пароля: {e}")
        return False


async def get_client_ip(request: Request) -> str:
    """
    Получает IP-адрес клиента (учитывает прокси).
    
    Args:
        request: FastAPI Request объект.
    
    Returns:
        str: IP-адрес клиента.
    """
    # Проверяем заголовки прокси
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # X-Forwarded-For может содержать несколько IP через запятую
        return forwarded.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    # Fallback на прямой IP
    return request.client.host if request.client else "unknown"


@app.post("/admin/auth", response_model=AuthResponse)
async def admin_auth(req: AuthRequest, request: Request):
    """
    Аутентификация администратора с защитой от брутфорса.
    
    Безопасность:
    - Пароль проверяется через bcrypt (хеш хранится в переменной окружения)
    - Rate limiting: 5 попыток, затем блокировка на 5 минут
    - JWT токен с истечением через 8 часов
    - Логирование попыток входа
    
    Returns:
        AuthResponse: {"status": "ok", "token": "...", "expires_in": 28800}
    
    Raises:
        HTTPException 401: Неверный пароль
        HTTPException 429: Слишком много попыток (rate limit)
        HTTPException 500: Ошибка конфигурации (хеш не установлен)
    """
    # Получаем IP клиента
    client_ip = await get_client_ip(request)
    
    # === ПРОВЕРКА RATE LIMIT ===
    if await login_rate_limiter.is_blocked(client_ip):
        remaining = login_rate_limiter.get_remaining_time(client_ip)
        logger.warning(f"🚫 Blocked login attempt from {client_ip} (rate limit)")
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много попыток входа. Повторите через {remaining} секунд."
        )
    
    # === ПРОВЕРКА КОНФИГУРАЦИИ ===
    if not ADMIN_PASSWORD_HASH:
        logger.error("❌ ADMIN_PASSWORD_HASH не установлен!")
        raise HTTPException(
            status_code=500,
            detail="Ошибка конфигурации сервера. Обратитесь к администратору."
        )
    
    # === ПРОВЕРКА ПАРОЛЯ ===
    if not verify_password(req.password, ADMIN_PASSWORD_HASH):
        # Записываем неудачную попытку
        await login_rate_limiter.record_attempt(client_ip)
        logger.warning(f"❌ Failed login attempt from {client_ip}")
        raise HTTPException(
            status_code=401,
            detail="Неверный пароль"
        )
    
    # === УСПЕШНАЯ АУТЕНТИФИКАЦИЯ ===
    # Очищаем историю попыток
    await login_rate_limiter.clear(client_ip)
    
    # Создаём JWT токен
    expires_delta = timedelta(hours=JWT_EXPIRE_HOURS)
    access_token = create_access_token(
        data={"sub": "admin", "ip": client_ip},
        expires_delta=expires_delta
    )
    
    logger.info(f"✅ Successful admin login from {client_ip}")
    
    return AuthResponse(
        status="ok",
        token=access_token,
        expires_in=int(expires_delta.total_seconds())
    )


async def verify_admin_token(request: Request) -> dict:
    """
    Проверяет JWT токен из заголовка Authorization.
    
    Используется как dependency для защищённых admin endpoints.
    Извлекает токен из заголовка "Authorization: Bearer <token>".
    
    Args:
        request: FastAPI Request объект.
    
    Returns:
        dict: Декодированный payload токена.
    
    Raises:
        HTTPException 401: Токен отсутствует, невалидный или истёк.
    """
    # Получаем заголовок Authorization
    auth_header = request.headers.get("Authorization")
    
    if not auth_header:
        raise HTTPException(
            status_code=401,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Проверяем формат "Bearer <token>"
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Неверный формат токена. Используйте: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = parts[1]
    
    try:
        # Декодируем и верифицируем токен
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )
        
        # Проверяем тип токена
        if payload.get("type") != "admin_access":
            raise HTTPException(
                status_code=401,
                detail="Неверный тип токена"
            )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Токен истёк. Пожалуйста, войдите снова.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise HTTPException(
            status_code=401,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"}
        )


# Dependency для защиты admin endpoints
async def admin_required(token_data: dict = Depends(verify_admin_token)) -> dict:
    """
    Dependency для защиты admin endpoints.
    
    Использование:
        @app.get("/admin/protected")
        async def protected_endpoint(admin: dict = Depends(admin_required)):
            ...
    
    Args:
        token_data: Декодированный JWT payload.
    
    Returns:
        dict: Данные администратора из токена.
    """
    return token_data


@app.get("/admin/collections")
async def admin_list_collections(admin: dict = Depends(admin_required)):
    """
    Получение списка всех коллекций для админ-панели.
    
    В отличие от /databases, возвращает ВСЕ коллекции,
    включая скрытые (visible=False).
    
    Требует JWT авторизации.
    
    Returns:
        {"collections": [список коллекций с полными метаданными]}
    """
    return {
        "collections": [
            {**meta, "is_active": name == db_manager.current_collection}
            for name, meta in db_manager.collections_metadata.items()
            if name != "_settings"  # Исключаем служебную секцию настроек
        ]
    }


@app.post("/admin/collections/{name}/config")
async def admin_update_config(name: str, config: CollectionConfig, admin: dict = Depends(admin_required)):
    """
    Обновление настроек коллекции (пороги, видимость).
    
    ВАЖНО: Флаг 'locked' НЕ может быть изменён через этот endpoint!
    Защита коллекции устанавливается только через прямое редактирование
    файла vector_databases.json.
    
    Требует JWT авторизации.
    
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
async def admin_delete_collection(name: str, admin: dict = Depends(admin_required)):
    """
    Полное удаление коллекции из Qdrant.
    
    ВНИМАНИЕ: Операция необратима! Все данные будут удалены.
    
    Защищённые коллекции (locked=True) НЕ могут быть удалены через API.
    Для снятия защиты необходимо вручную изменить файл vector_databases.json.
    
    Требует JWT авторизации.
    
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


# === УПРАВЛЕНИЕ СТАТУСАМИ ЗАПИСЕЙ ===

@app.get("/admin/statuses")
async def admin_get_statuses():
    """
    Получить список доступных статусов для записей.
    
    Статусы хранятся в секции _settings файла vector_databases.json.
    Этот эндпоинт публичный (без авторизации) для загрузки в UI.
    
    Returns:
        {
            "statuses": [{"id": "active", "label": "Активная", "color": "#10b981"}, ...],
            "default_status": "active"
        }
    """
    try:
        # Читаем секцию _settings из конфигурации
        settings = db_manager.collections_metadata.get("_settings", {})
        
        # Возвращаем статусы с дефолтными значениями если не настроены
        return {
            "statuses": settings.get("statuses", [
                {"id": "active", "label": "Активная", "color": "#10b981"},
                {"id": "draft", "label": "Черновик", "color": "#f59e0b"},
                {"id": "deprecated", "label": "Устаревшая", "color": "#ef4444"}
            ]),
            "default_status": settings.get("default_status", "active")
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статусов: {e}")
        # Возвращаем дефолтные статусы при ошибке
        return {
            "statuses": [
                {"id": "active", "label": "Активная", "color": "#10b981"},
                {"id": "draft", "label": "Черновик", "color": "#f59e0b"},
                {"id": "deprecated", "label": "Устаревшая", "color": "#ef4444"}
            ],
            "default_status": "active"
        }


class StatusConfig(BaseModel):
    """Конфигурация одного статуса"""
    id: str
    label: str
    color: str


class StatusesUpdateRequest(BaseModel):
    """Запрос на обновление списка статусов"""
    statuses: List[StatusConfig]
    default_status: str = "active"


@app.put("/admin/statuses")
async def admin_update_statuses(req: StatusesUpdateRequest, admin: dict = Depends(admin_required)):
    """
    Обновить список статусов для записей.
    
    Требует JWT авторизации.
    
    Args:
        req: Новый список статусов и статус по умолчанию
    
    Returns:
        {"status": "success", "statuses": [...], "default_status": "..."}
    """
    try:
        # Преобразуем статусы в словари
        statuses_list = [{"id": s.id, "label": s.label, "color": s.color} for s in req.statuses]
        
        # Проверяем что default_status есть в списке
        status_ids = [s.id for s in req.statuses]
        if req.default_status not in status_ids:
            raise HTTPException(400, f"default_status '{req.default_status}' не найден в списке статусов")
        
        # Обновляем секцию _settings
        if "_settings" not in db_manager.collections_metadata:
            db_manager.collections_metadata["_settings"] = {}
        
        db_manager.collections_metadata["_settings"]["statuses"] = statuses_list
        db_manager.collections_metadata["_settings"]["default_status"] = req.default_status
        
        # Сохраняем конфигурацию
        db_manager.save_configuration()
        
        logger.info(f"✅ Статусы обновлены: {len(statuses_list)} шт., default={req.default_status}")
        
        return {
            "status": "success",
            "statuses": statuses_list,
            "default_status": req.default_status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка обновления статусов: {e}")
        raise HTTPException(500, str(e))


# === НАСТРОЙКИ OPENROUTER ДЛЯ ГЕНЕРАЦИИ ЭМБЕДДИНГОВ ===

class OpenRouterSettings(BaseModel):
    """Модель настроек OpenRouter для генерации эмбеддингов"""
    enabled: bool = False
    api_key: str = ""
    model: str = "qwen/qwen3-embedding-4b"


class OpenRouterSettingsUpdate(BaseModel):
    """Запрос на обновление настроек OpenRouter"""
    enabled: bool = False
    api_key: str = ""
    model: str = "qwen/qwen3-embedding-4b"


@app.get("/admin/openrouter-settings")
async def admin_get_openrouter_settings():
    """
    Получить текущие настройки OpenRouter для генерации эмбеддингов.
    
    Настройки хранятся в секции _settings.openrouter файла vector_databases.json.
    Этот эндпоинт публичный (без авторизации) для загрузки настроек в UI.
    
    Returns:
        {
            "enabled": false,
            "api_key": "sk-..." (маскированный, показываются только последние 4 символа),
            "model": "qwen/qwen3-embedding-4b"
        }
    """
    try:
        # Читаем секцию _settings из конфигурации
        settings = db_manager.collections_metadata.get("_settings", {})
        openrouter = settings.get("openrouter", {})
        
        # Маскируем API ключ для безопасности (показываем только последние 4 символа)
        api_key = openrouter.get("api_key", "")
        masked_key = ""
        if api_key:
            masked_key = "*" * max(0, len(api_key) - 4) + api_key[-4:] if len(api_key) > 4 else "*" * len(api_key)
        
        return {
            "enabled": openrouter.get("enabled", False),
            "api_key": masked_key,  # Маскированный ключ
            "api_key_set": bool(api_key),  # Флаг: установлен ли ключ
            "model": openrouter.get("model", "qwen/qwen3-embedding-4b")
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения настроек OpenRouter: {e}")
        return {
            "enabled": False,
            "api_key": "",
            "api_key_set": False,
            "model": "qwen/qwen3-embedding-4b"
        }


@app.put("/admin/openrouter-settings")
async def admin_update_openrouter_settings(req: OpenRouterSettingsUpdate, admin: dict = Depends(admin_required)):
    """
    Обновить настройки OpenRouter для генерации эмбеддингов.
    
    Требует JWT авторизации.
    
    Args:
        req: Новые настройки OpenRouter (enabled, api_key, model)
    
    Returns:
        {"status": "success", "enabled": bool, "model": str, "api_key_set": bool}
    """
    try:
        # Инициализируем секцию _settings если не существует
        if "_settings" not in db_manager.collections_metadata:
            db_manager.collections_metadata["_settings"] = {}
        
        # Инициализируем секцию openrouter если не существует
        if "openrouter" not in db_manager.collections_metadata["_settings"]:
            db_manager.collections_metadata["_settings"]["openrouter"] = {}
        
        openrouter_settings = db_manager.collections_metadata["_settings"]["openrouter"]
        
        # Обновляем enabled и model
        openrouter_settings["enabled"] = req.enabled
        openrouter_settings["model"] = req.model
        
        # Обновляем API key только если передан непустой и не маскированный
        # (маскированный ключ содержит звёздочки)
        if req.api_key and "*" not in req.api_key:
            openrouter_settings["api_key"] = req.api_key
        
        # Сохраняем конфигурацию
        db_manager.save_configuration()
        
        logger.info(f"✅ Настройки OpenRouter обновлены: enabled={req.enabled}, model={req.model}")
        
        return {
            "status": "success",
            "enabled": openrouter_settings["enabled"],
            "model": openrouter_settings["model"],
            "api_key_set": bool(openrouter_settings.get("api_key", ""))
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка обновления настроек OpenRouter: {e}")
        raise HTTPException(500, str(e))


@app.get("/admin/embedding_dimension")
async def admin_get_embedding_dimension(admin: dict = Depends(admin_required)):
    """
    Получить текущую размерность эмбеддингов.
    
    Автоматически определяет размерность на основе активного провайдера:
    - OpenRouter API: размерность модели (обычно 2560 для Qwen)
    - Локальная модель: 1024
    
    Используется при создании новых коллекций.
    
    Returns:
        {"dimension": 2560, "provider": "openrouter" | "local", "model": "..."}
    """
    try:
        dimension = db_manager.get_embedding_dimension()
        
        if db_manager._is_openrouter_enabled():
            or_settings = db_manager._get_openrouter_settings()
            return {
                "dimension": dimension,
                "provider": "openrouter",
                "model": or_settings.get("model", "unknown")
            }
        else:
            return {
                "dimension": dimension,
                "provider": "local",
                "model": "qwen-embedding-local"
            }
    except Exception as e:
        logger.error(f"❌ Ошибка получения размерности: {e}")
        raise HTTPException(500, str(e))


@app.post("/admin/openrouter-test")
async def admin_test_openrouter_connection(admin: dict = Depends(admin_required)):
    """
    Проверить подключение к OpenRouter API.
    
    Выполняет тестовый запрос к API с текущими сохранёнными настройками.
    Требует JWT авторизации.
    
    Returns:
        {"status": "success", "message": "..."}  при успешном подключении
        {"status": "error", "message": "..."}  при ошибке
    """
    try:
        # Получаем настройки OpenRouter
        settings = db_manager.collections_metadata.get("_settings", {})
        openrouter = settings.get("openrouter", {})
        
        api_key = openrouter.get("api_key", "")
        model = openrouter.get("model", "qwen/qwen3-embedding-4b")
        
        if not api_key:
            return {"status": "error", "message": "API ключ не установлен"}
        
        # Тестовый запрос к OpenRouter API
        import httpx
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://ksr-matcher.local",  # Опционально для OpenRouter
                    "X-Title": "KSR Matcher"  # Опционально для OpenRouter
                },
                json={
                    "model": model,
                    "input": "test connection",
                    "encoding_format": "float"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                # Проверяем что получили эмбеддинг
                if "data" in data and len(data["data"]) > 0:
                    embedding_dim = len(data["data"][0].get("embedding", []))
                    return {
                        "status": "success",
                        "message": f"OK! Размерность: {embedding_dim}"
                    }
                else:
                    return {"status": "error", "message": "Неожиданный формат ответа от API"}
            elif response.status_code == 401:
                return {"status": "error", "message": "Неверный API ключ"}
            elif response.status_code == 404:
                return {"status": "error", "message": f"Модель '{model}' не найдена"}
            else:
                error_detail = response.text[:200] if response.text else "Неизвестная ошибка"
                return {"status": "error", "message": f"Ошибка API ({response.status_code}): {error_detail}"}
                
    except httpx.TimeoutException:
        return {"status": "error", "message": "Таймаут подключения к OpenRouter API"}
    except httpx.ConnectError:
        return {"status": "error", "message": "Не удалось подключиться к OpenRouter API"}
    except Exception as e:
        logger.error(f"❌ Ошибка тестирования OpenRouter: {e}")
        return {"status": "error", "message": f"Ошибка: {str(e)}"}


@app.get("/admin/collections/{name}/data")
async def admin_get_data(name: str, limit: int = 50, offset: str = None, admin: dict = Depends(admin_required)):
    """
    Пагинированный просмотр записей коллекции.
    
    Использует scroll API Qdrant для эффективной постраничной навигации.
    Требует JWT авторизации.
    
    Args:
        name: Имя коллекции
        limit: Количество записей на страницу (default: 50)
        offset: Токен следующей страницы (из предыдущего ответа)
    
    Returns:
        {
            "data": [список записей],
            "next_offset": токен для следующей страницы или null,
            "total": общее количество записей,
            "max_path_depth": максимальная глубина иерархии в коллекции
        }
    """
    if name not in db_manager.collections_metadata:
        raise HTTPException(404, "Collection not found")
        
    try:
        # === ФИЛЬТР: Исключаем записи папок (is_folder=true) ===
        # Папки - это технические записи для векторного поиска по каталогу
        # Они не должны отображаться в таблице "Данные"
        folder_exclusion_filter = Filter(
            must_not=[
                FieldCondition(
                    key="is_folder",
                    match=MatchValue(value=True)
                )
            ]
        )
        
        # Используем scroll api с фильтром исключения папок
        points, next_offset = db_manager.client.scroll(
            collection_name=name,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
            scroll_filter=folder_exclusion_filter
        )
        
        columns = db_manager.collections_metadata[name]["columns"]
        
        # === НОВОЕ: Вычисляем max_path_depth по всем записям батча ===
        # Это нужно для корректного отображения всех уровней категорий в таблице админки
        max_path_depth = 0
        
        data = []
        for p in points:
            # Получаем path_depth из payload для определения максимальной глубины
            point_depth = p.payload.get("path_depth", 0)
            if point_depth > max_path_depth:
                max_path_depth = point_depth
            
            data.append({
                "id": p.id,
                "code": p.payload.get(columns["code"]),
                "description": p.payload.get(columns["description"]),
                "meta": p.payload
            })
        
        # Если max_path_depth всё ещё 0, пробуем найти path_level_N в первой записи (fallback)
        # Это для обратной совместимости со старыми записями без path_depth
        if max_path_depth == 0 and data:
            first_meta = data[0].get("meta", {})
            for i in range(1, 11):  # Проверяем до 10 уровней
                if f"path_level_{i}" in first_meta and first_meta[f"path_level_{i}"]:
                    max_path_depth = i
            
        return {
            "data": data,
            "next_offset": next_offset,
            "total": db_manager.collections_metadata[name]["record_count"],
            "max_path_depth": max_path_depth  # Максимальная глубина иерархии для таблицы
        }
    except Exception as e:
        raise HTTPException(500, str(e))

def rebuild_context_description(payload: dict, separator: str = "→") -> str:
    """
    Пересобирает context_description из полей path_level_N и full_description.
    
    Используется при редактировании отдельных уровней категорий.
    
    Args:
        payload: Текущий payload записи с path_level_N и full_description.
        separator: Разделитель уровней (по умолчанию "→").
    
    Returns:
        str: Полный контекстный путь для эмбеддинга.
    """
    # Собираем все уровни категорий в порядке
    path_depth = payload.get("path_depth", 0)
    categories = []
    
    for i in range(1, path_depth + 1):
        level_value = payload.get(f"path_level_{i}", "")
        if level_value:
            categories.append(level_value)
    
    # Получаем полное описание материала
    full_description = payload.get("full_description", "")
    
    # Собираем контекстное описание: категории + описание
    if categories and full_description:
        context = f" {separator} ".join(categories) + f" {separator} " + full_description
    elif categories:
        context = f" {separator} ".join(categories)
    else:
        context = full_description
    
    return context


@app.post("/admin/collections/{name}/data/{id}")
async def admin_update_point(name: str, id: str, req: UpdatePointRequest, admin: dict = Depends(admin_required)):
    """
    Редактирование конкретной ячейки. Требует JWT авторизации.
    
    НОВАЯ ЛОГИКА v2: Поддержка редактирования уровней категорий (path_level_N),
    полного описания (full_description) и пересчёт эмбеддингов.
    
    При изменении path_level_N или full_description:
    - Пересобирается context_description
    - Пересчитывается эмбеддинг
    - Обновляется legacy поле description
    """
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
    payload = dict(point.payload)  # Копируем для изменений
    vector = point.vector
    need_reembed = False  # Флаг: нужно ли пересчитать эмбеддинг
    need_cache_invalidate = False  # Флаг: нужно ли инвалидировать кэш иерархии
    need_folder_sync = False  # Флаг: нужно ли синхронизировать папки
    
    # Запоминаем старый путь папки ДО изменений (для синхронизации папок)
    old_folder_path = build_full_path_from_payload(payload)
    
    # Запоминаем folder_ids и пути ДО изменений (для корректной синхронизации всех уровней)
    old_folder_ids = payload.get("folder_ids", [])
    old_folder_paths = []
    # Вычисляем пути для каждого уровня
    path_depth = payload.get("path_depth", 0)
    if path_depth > 0:
        parts = []
        for lvl in range(1, path_depth + 1):
            part = payload.get(f"path_level_{lvl}", "")
            if part:
                parts.append(part)
                old_folder_paths.append(" → ".join(parts))
    
    # Обновляем поле
    if req.field == "description":
        # Legacy режим: меняется полное описание (как раньше)
        # Пересчитываем все path_levels из нового описания
        new_text = req.value
        path_levels = generate_path_levels(new_text, separator="→")
        payload.update(path_levels)
        payload[columns["description"]] = new_text
        need_reembed = True
        need_cache_invalidate = True
        
    elif req.field == "full_description":
        # Изменение полного описания материала
        payload["full_description"] = req.value
        # Пересобираем context_description
        payload["context_description"] = rebuild_context_description(payload)
        # Обновляем legacy description
        payload[columns["description"]] = payload["context_description"]
        need_reembed = True
        need_cache_invalidate = True
        
    elif req.field.startswith("path_level_"):
        # Изменение уровня категории
        level_num = int(req.field.split("_")[-1])
        payload[req.field] = req.value
        
        # Если добавляем новый уровень, увеличиваем path_depth
        current_depth = payload.get("path_depth", 0)
        if level_num > current_depth:
            payload["path_depth"] = level_num
        
        # Пересобираем context_description
        payload["context_description"] = rebuild_context_description(payload)
        # Обновляем legacy description
        payload[columns["description"]] = payload["context_description"]
        
        # === ПЕРЕСЧЁТ folder_ids ===
        # При изменении path_level_N нужно обновить массив ID связанных папок
        path_depth = payload.get("path_depth", 0)
        folder_ids = []
        if path_depth > 0:
            parts = []
            for lvl in range(1, path_depth + 1):
                part = payload.get(f"path_level_{lvl}", "")
                if part:
                    parts.append(part)
                    folder_full_path = " → ".join(parts)
                    folder_code_str = f"folder::{folder_full_path.replace(' → ', '::')}"
                    folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code_str))
                    folder_ids.append(folder_id)
        payload["folder_ids"] = folder_ids
        
        need_reembed = True
        need_cache_invalidate = True
        need_folder_sync = True  # Нужна синхронизация папок!
        
    elif req.field == "code":
        payload[columns["code"]] = req.value
        # Вектор не меняется, но кэш нужно инвалидировать (код в каталоге)
        need_cache_invalidate = True
        
    elif req.field == "status":
        # Изменение статуса записи - только обновляем метаданные
        payload["status"] = req.value
        # Статус не влияет на эмбеддинги и кэш иерархии
        
    else:
        # Произвольное поле меты
        payload[req.field] = req.value
    
    # === ОБНОВЛЕНИЕ МЕТАДАННЫХ ВЕРСИОНИРОВАНИЯ ===
    # При ЛЮБОМ изменении обновляем дату и инкрементируем версию
    from datetime import datetime
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    # Для записей без версии (старые записи) считаем что текущая версия = 1
    # При первом изменении версия станет 2
    current_version = payload.get("version") or 1
    payload["version"] = current_version + 1
    
    # Пересчитываем эмбеддинг если нужно
    if need_reembed:
        context_text = payload.get("context_description", payload.get(columns["description"], ""))
        async with db_manager.gpu_lock:
            emb = await db_manager.get_embedding_cached(context_text)
            vector = emb.tolist() if isinstance(emb, np.ndarray) else emb
        
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
    
    # Инвалидируем кэш иерархии если изменились данные, влияющие на каталог
    if need_cache_invalidate:
        hierarchy_service.invalidate_cache(name)
        logger.info(f"🗑️ Hierarchy cache invalidated after edit: {name}")
    
    # === СИНХРОНИЗАЦИЯ ПАПОК ===
    # При изменении path_level_N нужно проверить и обновить записи папок
    folder_sync_result = None
    if need_folder_sync:
        # Получаем новые folder_ids и пути из обновлённого payload
        new_folder_ids = payload.get("folder_ids", [])
        new_folder_paths = []
        new_path_depth = payload.get("path_depth", 0)
        if new_path_depth > 0:
            parts = []
            for lvl in range(1, new_path_depth + 1):
                part = payload.get(f"path_level_{lvl}", "")
                if part:
                    parts.append(part)
                    new_folder_paths.append(" → ".join(parts))
        
        # Вызываем новую функцию с folder_ids для ВСЕХ уровней иерархии
        if old_folder_ids != new_folder_ids or old_folder_paths != new_folder_paths:
            logger.info(f"📁 Синхронизация папок: {len(old_folder_ids)} → {len(new_folder_ids)} уровней")
            folder_sync_result = await sync_folders_after_material_edit(
                db_manager, name,
                old_folder_ids, new_folder_ids,
                old_folder_paths, new_folder_paths
            )
    
    response = {
        "status": "success", 
        "context_description": payload.get("context_description"),
        # === НОВОЕ: Возвращаем обновлённые метаданные версионирования ===
        "updated_at": payload.get("updated_at"),
        "version": payload.get("version"),
        "id": id  # ID записи для точного сопоставления на клиенте
    }
    
    if folder_sync_result:
        response["folder_sync"] = folder_sync_result
    
    return response

@app.delete("/admin/collections/{name}/data/{id}")
async def admin_delete_point(name: str, id: str, admin: dict = Depends(admin_required)):
    """
    Удаление точки из коллекции Qdrant.
    
    НОВАЯ ЛОГИКА: После удаления материала проверяем и удаляем осиротевшие папки.
    Используем folder_ids из payload материала для быстрого поиска связанных папок.
    
    Args:
        name: Имя коллекции
        id: UUID точки в Qdrant (строка)
    
    Требует JWT авторизации.
    """
    try:
        logger.info(f"🗑️ Удаление точки id={id} из коллекции '{name}'")
        
        # === ШАГ 1: Получаем payload материала ПЕРЕД удалением ===
        # Нужен для получения folder_ids и path_levels
        points = db_manager.client.retrieve(
            collection_name=name,
            ids=[id],
            with_payload=True,
            with_vectors=False
        )
        
        folder_ids_to_check = []
        path_levels_to_check = []
        
        if points:
            payload = points[0].payload
            folder_ids_to_check = payload.get("folder_ids", [])
            
            # Собираем path_levels для проверки (fallback если нет folder_ids)
            path_depth = payload.get("path_depth", 0)
            if path_depth > 0:
                parts = []
                for lvl in range(1, path_depth + 1):
                    part = payload.get(f"path_level_{lvl}", "")
                    if part:
                        parts.append(part)
                        path_levels_to_check.append(" → ".join(parts))
            
            logger.info(f"📁 Связанные папки материала: {len(folder_ids_to_check)} шт.")
        
        # === ШАГ 2: Удаляем сам материал ===
        db_manager.client.delete(
            collection_name=name,
            points_selector=[id]
        )
        
        # Обновляем счетчик
        if name in db_manager.collections_metadata:
            db_manager.collections_metadata[name]["record_count"] -= 1
            logger.info(f"✅ Точка {id} удалена, осталось записей: {db_manager.collections_metadata[name]['record_count']}")
        
        # === ШАГ 3: Проверяем и удаляем осиротевшие папки ===
        deleted_folders = []
        
        # Проверяем каждую папку из path_levels (от самой глубокой к корневой)
        for full_path in reversed(path_levels_to_check):
            parts = full_path.split(" → ")
            
            # Строим фильтр для подсчёта материалов в этой папке
            filter_conditions = []
            for i, part in enumerate(parts):
                filter_conditions.append(
                    FieldCondition(
                        key=f"path_level_{i + 1}",
                        match=MatchValue(value=part)
                    )
                )
            
            try:
                count_result = db_manager.client.count(
                    collection_name=name,
                    count_filter=Filter(
                        must=filter_conditions,
                        must_not=[
                            FieldCondition(
                                key="is_folder",
                                match=MatchValue(value=True)
                            )
                        ]
                    )
                )
                materials_count = count_result.count
                
                if materials_count == 0:
                    # Папка осиротела - удаляем
                    folder_code = f"folder::{full_path.replace(' → ', '::')}"
                    folder_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, folder_code))
                    
                    db_manager.client.delete(
                        collection_name=name,
                        points_selector=[folder_id]
                    )
                    deleted_folders.append(full_path)
                    logger.info(f"🗑️ Удалена осиротевшая папка: {full_path}")
                else:
                    # Если папка не пустая, родительские тоже не пустые - прекращаем
                    break
                    
            except Exception as e:
                logger.warning(f"⚠️ Ошибка проверки папки '{full_path}': {e}")
        
        # Инвалидируем кэш иерархии для этой коллекции
        if name in hierarchy_service.children_cache:
            keys_to_delete = [k for k in hierarchy_service.children_cache.keys() if k.startswith(name)]
            for key in keys_to_delete:
                del hierarchy_service.children_cache[key]
            logger.info(f"🧹 Очищен кэш иерархии ({len(keys_to_delete)} ключей)")
        
        return {
            "status": "success", 
            "deleted_id": id,
            "deleted_folders": deleted_folders
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка удаления точки {id}: {str(e)}")
        raise HTTPException(500, str(e))

@app.post("/admin/import")
async def admin_import_data(req: dict, admin: dict = Depends(admin_required)):
    """
    Старт фоновой задачи импорта.
    Требует JWT авторизации.
    
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


# === ЗАГРУЗКА EXCEL ФАЙЛОВ ===

@app.post("/admin/upload_excel")
async def admin_upload_excel(
    file: UploadFile = File(...),
    sheet: Optional[str] = None,
    admin: dict = Depends(admin_required)
):
    """
    Загрузка и парсинг Excel файла.
    
    Позволяет выбрать лист для парсинга если в файле несколько листов.
    Возвращает заголовки колонок и preview первых строк для маппинга.
    
    Args:
        file: Excel файл (.xlsx, .xls)
        sheet: Имя листа для парсинга (по умолчанию - первый лист)
    
    Returns:
        {
            "sheets": ["Лист1", "Лист2"],
            "selected_sheet": "Лист1",
            "headers": ["Код", "Наименование", ...],
            "preview": [{...}, {...}, ...],
            "total_rows": 12500
        }
    """
    import pandas as pd
    
    # Проверяем расширение файла
    filename = file.filename or ""
    if not filename.lower().endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Поддерживаются только файлы Excel (.xlsx, .xls)")
    
    try:
        content = await file.read()
        xlsx = pd.ExcelFile(io.BytesIO(content), engine='openpyxl')
        
        sheet_names = xlsx.sheet_names
        selected = sheet if sheet and sheet in sheet_names else sheet_names[0]
        
        # Читаем выбранный лист
        df = pd.read_excel(
            xlsx, 
            sheet_name=selected, 
            dtype=str,  # Всё как строки для сохранения ведущих нулей
            na_values=["", "N/A", "NULL", "—", "–", "-"],
            keep_default_na=True
        )
        
        # Заменяем NaN на пустые строки для JSON сериализации
        df = df.fillna("")
        
        # Сохраняем ВСЕ данные в кэш для последующего импорта
        # Используем уникальный ключ на основе имени файла и времени
        import hashlib
        cache_key = hashlib.md5(f"{filename}_{time.time()}".encode()).hexdigest()[:16]
        
        # Глобальный кэш для Excel данных (создаём если не существует)
        if not hasattr(app.state, 'excel_cache'):
            app.state.excel_cache = {}
        
        # Ограничиваем размер кэша (максимум 5 файлов)
        if len(app.state.excel_cache) >= 5:
            # Удаляем самый старый
            oldest_key = next(iter(app.state.excel_cache))
            del app.state.excel_cache[oldest_key]
        
        # Сохраняем все данные
        all_records = df.to_dict(orient='records')
        app.state.excel_cache[cache_key] = {
            "headers": df.columns.tolist(),
            "data": all_records,
            "filename": filename,
            "timestamp": time.time()
        }
        
        # Формируем preview (первые 100 строк для UI)
        preview_df = df.head(100)
        
        # === ПРИМЕНЯЕМ ПРАВИЛА ОЧИСТКИ К PREVIEW ===
        # Это позволяет пользователю сразу видеть как будут выглядеть данные после очистки
        cleaned_preview = []
        preview_records = preview_df.to_dict(orient='records')
        
        # Получаем правила очистки
        settings = db_manager.collections_metadata.get("_settings", {})
        rules = settings.get("cleaning_rules", DEFAULT_CLEANING_RULES)
        
        for row in preview_records:
            cleaned_row = {}
            for col_name, value in row.items():
                if isinstance(value, str) and value:
                    # Применяем все активные правила
                    cleaned_value = value
                    for rule in rules:
                        if not rule.get("enabled", True):
                            continue
                        apply_to = rule.get("apply_to_columns", ["*"])
                        if "*" not in apply_to and col_name not in apply_to:
                            continue
                        try:
                            pattern = rule.get("pattern", "")
                            replacement = rule.get("replacement", "")
                            cleaned_value = re.sub(pattern, replacement, cleaned_value)
                        except re.error:
                            pass  # Игнорируем невалидные regex
                    cleaned_row[col_name] = cleaned_value.strip()
                else:
                    cleaned_row[col_name] = value
            cleaned_preview.append(cleaned_row)
        
        logger.info(f"📊 Excel загружен: {filename}, лист '{selected}', "
                   f"{len(df)} строк, {len(df.columns)} колонок. Cache key: {cache_key}")
        
        return {
            "filename": filename,
            "sheets": sheet_names,
            "selected_sheet": selected,
            "headers": df.columns.tolist(),
            "preview": cleaned_preview,  # Очищенные данные для preview!
            "preview_raw": preview_records,  # Сырые данные для сравнения
            "total_rows": len(df),
            "cache_key": cache_key  # Ключ для получения всех данных
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга Excel: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Ошибка парсинга Excel: {str(e)}")


@app.get("/admin/excel_data/{cache_key}")
async def admin_get_excel_data(
    cache_key: str,
    admin: dict = Depends(admin_required)
):
    """
    Получить все данные Excel из кэша.
    
    Используется при импорте для получения всех строк (не только preview).
    Cache_key возвращается из /admin/upload_excel.
    
    Returns:
        {"headers": [...], "data": [{...}, ...], "total_rows": N}
    """
    if not hasattr(app.state, 'excel_cache') or cache_key not in app.state.excel_cache:
        raise HTTPException(404, f"Данные не найдены в кэше. Загрузите файл заново.")
    
    cached = app.state.excel_cache[cache_key]
    
    logger.info(f"📊 Выдача данных из кэша: {cache_key}, {len(cached['data'])} строк")
    
    return {
        "headers": cached["headers"],
        "data": cached["data"],
        "total_rows": len(cached["data"]),
        "filename": cached.get("filename", "unknown")
    }


# === ПРАВИЛА ОЧИСТКИ ДАННЫХ ===

class CleaningRule(BaseModel):
    """Правило очистки текстовых данных при импорте"""
    id: str
    name: str
    pattern: str  # Regex паттерн
    replacement: str = ""  # Замена (по умолчанию удаление)
    enabled: bool = True
    apply_to_columns: List[str] = ["*"]  # ["*"] = все колонки


# Правила очистки по умолчанию
DEFAULT_CLEANING_RULES = [
    {
        "id": "remove_section_prefix",
        "name": "Удалить 'Раздел/Группа N.N'",
        "pattern": r"^(Раздел|Группа)\s+[\d\.\s]+",
        "replacement": "",
        "enabled": True,
        "apply_to_columns": ["*"]
    }
]


@app.get("/admin/cleaning_rules")
async def admin_get_cleaning_rules():
    """
    Получить список правил очистки данных.
    
    Правила применяются при импорте данных ко всем текстовым полям.
    Этот эндпоинт публичный для загрузки в UI.
    
    Returns:
        {"rules": [CleaningRule, ...]}
    """
    settings = db_manager.collections_metadata.get("_settings", {})
    rules = settings.get("cleaning_rules", DEFAULT_CLEANING_RULES)
    return {"rules": rules}


@app.put("/admin/cleaning_rules")
async def admin_update_cleaning_rules(
    rules: List[CleaningRule],
    admin: dict = Depends(admin_required)
):
    """
    Обновить список правил очистки данных.
    
    Требует JWT авторизации.
    
    Args:
        rules: Новый список правил очистки
    
    Returns:
        {"status": "success", "rules": [...]}
    """
    try:
        # Проверяем валидность regex-паттернов
        for rule in rules:
            try:
                re.compile(rule.pattern)
            except re.error as e:
                raise HTTPException(400, f"Невалидный regex в правиле '{rule.name}': {e}")
        
        # Сохраняем в _settings
        if "_settings" not in db_manager.collections_metadata:
            db_manager.collections_metadata["_settings"] = {}
        
        db_manager.collections_metadata["_settings"]["cleaning_rules"] = [
            r.dict() for r in rules
        ]
        db_manager.save_configuration()
        
        logger.info(f"✅ Обновлены правила очистки: {len(rules)} правил")
        
        return {"status": "success", "rules": [r.dict() for r in rules]}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка обновления правил очистки: {e}")
        raise HTTPException(500, str(e))


def apply_cleaning_rules(text: str, column_name: str = None) -> str:
    """
    Применяет все активные правила очистки к тексту.
    
    Args:
        text: Исходный текст
        column_name: Имя колонки (для фильтрации правил по apply_to_columns)
    
    Returns:
        Очищенный текст
    """
    import pandas as pd
    
    if pd.isna(text) or text == "":
        return ""
    
    result = str(text)
    settings = db_manager.collections_metadata.get("_settings", {})
    rules = settings.get("cleaning_rules", DEFAULT_CLEANING_RULES)
    
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        
        apply_to = rule.get("apply_to_columns", ["*"])
        if "*" not in apply_to and column_name and column_name not in apply_to:
            continue
        
        try:
            pattern = rule.get("pattern", "")
            replacement = rule.get("replacement", "")
            result = re.sub(pattern, replacement, result)
        except re.error:
            pass  # Игнорируем невалидные regex
    
    return result.strip()

@app.get("/admin/jobs")
async def admin_list_jobs(admin: dict = Depends(admin_required)):
    """Получение списка фоновых задач. Требует JWT авторизации."""
    return await job_manager.list_jobs()


@app.post("/admin/jobs/{job_id}/stop")
async def admin_stop_job(job_id: str, admin: dict = Depends(admin_required)):
    """Остановка фоновой задачи"""
    success = await job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Невозможно остановить задачу (не найдена или уже завершена)")
    
    return {"status": "success", "message": f"Задача {job_id} остановлена"}


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

            # === ФИЛЬТР: Исключаем записи папок (is_folder=true) ===
            # При сравнении с базой папки не должны учитываться,
            # так как они управляются автоматически на основе материалов
            folder_exclusion_filter = Filter(
                must_not=[
                    FieldCondition(
                        key="is_folder",
                        match=MatchValue(value=True)
                    )
                ]
            )
            
            # Запрашиваем батч записей из Qdrant (без папок)
            # ВАЖНО: Для сравнения используем full_description (короткое имя материала),
            # а не description (полный контекстный путь для эмбеддингов)
            scroll_result = await loop.run_in_executor(
                db_manager.executor,
                lambda: db_manager.client.scroll(
                    collection_name=collection_name,
                    limit=10000,  # Внутренний батч для производительности
                    offset=offset,
                    with_payload=[
                        "code",
                        "full_description",  # Короткое имя материала для сравнения
                        "description",       # Fallback для старых записей
                    ],
                    with_vectors=False,  # Векторы не нужны (экономия памяти)
                    scroll_filter=folder_exclusion_filter,  # Исключаем папки
                ),
            )

            points, offset = scroll_result

            # Извлекаем код и описание из каждой точки
            # Приоритет: full_description > description (для обратной совместимости)
            for point in points:
                code = point.payload.get("code")
                # Используем full_description (короткое имя материала) для сравнения
                # Fallback на description для старых записей без full_description
                material_name = point.payload.get("full_description") or point.payload.get("description")

                if code and material_name:
                    all_records[code] = material_name

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


@app.get("/get_all_folders")
async def get_all_folders(database: Optional[str] = None):
    """
    Получение списка ВСЕХ папок (записей с is_folder=true) из коллекции.
    
    Возвращает словарь {full_path: {leaf_name, items_count, path_levels}} для отображения
    в diff-анализе и для сравнения изменений папок.
    
    Args:
        database: Название коллекции (если не указано - используется текущая активная)
    
    Returns:
        {
            "status": "success",
            "collection": "ksr_main",
            "folders": {
                "Приборы → Аннотации": {"leaf_name": "Аннотации", "items_count": 42, "id": "uuid"},
                ...
            },
            "total": 1205,
            "elapsed_seconds": 1.24
        }
    """
    try:
        collection_name = database or db_manager.current_collection
        
        if not collection_name:
            raise HTTPException(status_code=400, detail="Коллекция не указана")
        
        logger.info(f"📁 Запрос ВСЕХ папок из '{collection_name}'...")
        start_time = time.time()
        
        loop = asyncio.get_event_loop()
        
        # === ФИЛЬТР: Выбираем ТОЛЬКО записи папок (is_folder=true) ===
        folder_filter = Filter(
            must=[
                FieldCondition(
                    key="is_folder",
                    match=MatchValue(value=True)
                )
            ]
        )
        
        # Собираем все папки в словарь {full_path: данные}
        all_folders = {}
        offset = None
        batch_count = 0
        
        # Цикл по всей коллекции батчами
        while True:
            batch_count += 1
            
            # Запрашиваем батч папок из Qdrant
            scroll_result = await loop.run_in_executor(
                db_manager.executor,
                lambda: db_manager.client.scroll(
                    collection_name=collection_name,
                    limit=10000,  # Внутренний батч для производительности
                    offset=offset,
                    with_payload=[
                        "full_path",
                        "leaf_name", 
                        "items_count",
                        "path_depth",
                        "code",
                    ],
                    with_vectors=False,
                    scroll_filter=folder_filter,
                ),
            )
            
            points, offset = scroll_result
            
            # Извлекаем данные папки из каждой точки
            for point in points:
                full_path = point.payload.get("full_path")
                
                if full_path:
                    all_folders[full_path] = {
                        "id": str(point.id),
                        "leaf_name": point.payload.get("leaf_name", ""),
                        "items_count": point.payload.get("items_count", 0),
                        "path_depth": point.payload.get("path_depth", 1),
                        "code": point.payload.get("code", ""),
                    }
            
            # Если offset None - достигли конца коллекции
            if offset is None:
                break
        
        elapsed = time.time() - start_time
        
        logger.info(
            f"✅ Собрано {len(all_folders)} папок за {elapsed:.2f}с "
            f"({batch_count} батчей)"
        )
        
        return {
            "status": "success",
            "collection": collection_name,
            "folders": all_folders,  # Словарь {full_path: данные}
            "total": len(all_folders),
            "elapsed_seconds": round(elapsed, 2),
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения папок: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Ошибка получения папок: {str(e)}"
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

        # Генерируем поля path_level_N для иерархической фильтрации
        # НОВАЯ ЛОГИКА v2: path_level_N содержит только своё название
        path_levels = generate_path_levels(request.description, separator="→")
        
        # Получаем context_description для эмбеддинга
        context_text = path_levels.get("context_description", request.description)
        
        # Генерация эмбеддинга из context_description (защищено GPU Lock)
        async with db_manager.gpu_lock:
            new_embedding = await db_manager.get_embedding_cached(context_text)
        
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
        
        # Подготовка метаданных
        new_metadata = {
            "code": request.code,
            "description": request.description,  # Legacy: сохраняем исходное описание
            **path_levels,  # path_level_N, path_depth, full_description, context_description
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
        # === ИСПРАВЛЕНИЕ: Используем get_embedding_dimension() для корректного определения размерности ===
        # Это работает и для OpenRouter API, и для локальной модели
        model_dimension = db_manager.get_embedding_dimension()
        logger.info(f"📐 Определена размерность модели: {model_dimension}")
        
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
        # === ИСПРАВЛЕНИЕ: Сохраняем dimension в конфигурацию ===
        config[request.collection_name] = {
            "description": request.description or f"Векторная база {request.collection_name}",
            "dimension": model_dimension,  # Размерность эмбеддингов!
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
    
    # === PRE-BUILD BM25 INDEX ===
    # Строим индекс при старте, чтобы первый запрос был быстрым
    if BM25_ENABLED:
        logger.info("📚 Построение BM25 индекса для активных коллекций...")
        for collection_name in db_manager.collections_metadata.keys():
            if collection_name == "_settings":
                continue
            try:
                db_manager._ensure_bm25_index(collection_name)
            except Exception as e:
                logger.warning(f"⚠️ Не удалось построить BM25 для '{collection_name}': {e}")
        logger.info("✅ BM25 индексы готовы")
    else:
        logger.info("⚠️ BM25 отключен (BM25_ENABLED=False в config.py)")
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
