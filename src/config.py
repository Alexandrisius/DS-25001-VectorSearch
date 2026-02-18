# config.py
"""
Конфигурация проекта KSR Vector Search.

Этот файл содержит все настраиваемые пути и параметры системы.
При развертывании на новой машине достаточно изменить только этот файл.

Автор: Alexandr
Дата: 01.12.2025
"""

import os
from pathlib import Path

# === КОРНЕВЫЕ ДИРЕКТОРИИ ===

# Автоматическое определение корня проекта (папка, содержащая src/)
# Работает независимо от того, откуда запущен скрипт
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Альтернативный путь (для жёсткой привязки к конкретной машине)
# Раскомментируйте и измените при необходимости:
# PROJECT_ROOT = Path("C:/Users/klim9/Yandex.Disk/02_Work/#Projects/04_DataScience/DS-25001-VectorSearch")


# === ПУТИ К ДАННЫМ ===

# Директория с данными
DATA_DIR = PROJECT_ROOT / "data"

# Сырые данные (Excel файлы)
RAW_DATA_DIR = DATA_DIR / "01_raw"

# Промежуточные данные (очищенные CSV)
INTERIM_DATA_DIR = DATA_DIR / "02_interim"

# Обработанные данные (Qdrant storage, эмбеддинги)
PROCESSED_DATA_DIR = DATA_DIR / "03_processed"

# Логи аналитики (feedback)
FEEDBACK_DIR = DATA_DIR / "04_feedback"

# Хранилище Qdrant
QDRANT_STORAGE_PATH = PROCESSED_DATA_DIR / "qdrant_storage"


# === ПУТИ К МОДЕЛЯМ ===

# Модель эмбеддингов Qwen3-Embedding-4B
# ВНИМАНИЕ: Измените на ваш локальный путь к модели!
QWEN_MODEL_PATH = r"D:\hf_cache\Qwen3-Embedding-4B"

# Модель реранкера BGE-M3
# ВНИМАНИЕ: Измените на ваш локальный путь к модели!
RERANKER_PATH = r"D:\hf_cache\bge-reranker-v2-m3"


# === ПУТИ К ВЕБ-ИНТЕРФЕЙСУ ===

# Директория с веб-файлами
WEB_DIR = PROJECT_ROOT / "web"

# Директория со статикой (CSS, JS, изображения)
STATIC_DIR = WEB_DIR / "static"


# === КОНФИГУРАЦИЯ СЕРВЕРА ===

# Файл конфигурации векторных баз
VECTOR_DATABASES_CONFIG = PROJECT_ROOT / "src" / "vector_databases.json"


# === ПАРАМЕТРЫ МОДЕЛЕЙ ===

# Максимальная длина токенов для модели эмбеддингов
MAX_TOKEN_LENGTH = 1024

# Размер батча для генерации эмбеддингов
EMBEDDING_BATCH_SIZE = 32

# Размер батча для загрузки в Qdrant
UPLOAD_BATCH_SIZE = 100

# Параметры для API OpenRouter (параллельная генерация)
# Уменьшенные значения для избежания rate limiting и ошибок "No successful provider"
API_EMBEDDING_BATCH_SIZE = 10  # было 100 - уменьшено для надёжности
API_MAX_WORKERS = 3  # было 10 - уменьшено для надёжности


# === ПАРАМЕТРЫ ПОИСКА (по умолчанию) ===

# Количество кандидатов из Qdrant (Stage 1)
DEFAULT_TOP_K_QDRANT = 500

# Количество кандидатов для реранкинга (Stage 2)
DEFAULT_MAX_FOR_RERANK = 100

# Максимальное количество результатов в ответе
DEFAULT_MAX_RESULTS = 100

# Пороги по умолчанию (переопределяются в vector_databases.json)
DEFAULT_COSINE_THRESHOLD = 0.45
DEFAULT_RERANK_THRESHOLD = 0.6


# === ГИБРИДНЫЙ ПОИСК (BM25 + Dense) ===

# Включить гибридный поиск (BM25 + Dense)?
# False = только векторный поиск (как было раньше)
BM25_ENABLED = True

# Количество кандидатов из BM25 (Stage 1 Sparse)
# BM25 Search мгновенный (~0.004s), можно брать много
BM25_TOP_K = 200

# Максимум уникальных BM25 записей для подгрузки payload
# Retrieve тоже быстрый (~0.001s для 30 записей)
BM25_MAX_RETRIEVE = 100

# Лимит кандидатов для Reranker после объединения Dense+BM25
# 200 = 100 dense + до 100 bm25 (reranker ~0.4s для 200 пар)
HYBRID_RERANK_LIMIT = 200


# === КЭШИРОВАНИЕ ===

# Максимальный размер LRU-кэша эмбеддингов
EMBEDDING_CACHE_SIZE = 15000


# === СЕРВЕР ===

# Хост и порт сервера
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000


# === БЕЗОПАСНОСТЬ АДМИН-ПАНЕЛИ ===

# Хеш пароля администратора (bcrypt)
# Генерируется скриптом: python scripts/service/generate_password_hash.py
# ВАЖНО: В продакшене установите через переменную окружения!
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

# Секретный ключ для подписи JWT токенов
# ВАЖНО: В продакшене замените на случайную строку минимум 32 символа!
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-use-random-32-chars")

# Алгоритм подписи JWT (HS256 - HMAC с SHA-256)
JWT_ALGORITHM = "HS256"

# Время жизни токена в часах (8 часов = рабочий день)
JWT_EXPIRE_HOURS = 8

# Защита от брутфорса: максимальное количество попыток входа
LOGIN_MAX_ATTEMPTS = 5

# Время блокировки после превышения попыток (в минутах)
LOGIN_LOCKOUT_MINUTES = 5


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def ensure_directories():
    """
    Создаёт все необходимые директории, если они не существуют.
    Вызывается при старте приложения.
    """
    directories = [
        RAW_DATA_DIR,
        INTERIM_DATA_DIR,
        PROCESSED_DATA_DIR,
        FEEDBACK_DIR,
        QDRANT_STORAGE_PATH,
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def validate_model_paths():
    """
    Проверяет наличие моделей по указанным путям.
    Возвращает список ошибок (пустой, если всё в порядке).
    """
    errors = []
    
    if not os.path.exists(QWEN_MODEL_PATH):
        errors.append(f"Модель эмбеддингов не найдена: {QWEN_MODEL_PATH}")
    
    if not os.path.exists(RERANKER_PATH):
        errors.append(f"Модель реранкера не найдена: {RERANKER_PATH}")
    
    return errors


# === ВЫВОД КОНФИГУРАЦИИ ПРИ ЗАПУСКЕ МОДУЛЯ ===

if __name__ == "__main__":
    print("=" * 60)
    print("🔧 КОНФИГУРАЦИЯ ПРОЕКТА KSR VECTOR SEARCH")
    print("=" * 60)
    print(f"📁 Корень проекта:     {PROJECT_ROOT}")
    print(f"📂 Данные:             {DATA_DIR}")
    print(f"🗃️ Qdrant Storage:     {QDRANT_STORAGE_PATH}")
    print(f"🧠 Модель эмбеддингов: {QWEN_MODEL_PATH}")
    print(f"🎯 Реранкер:           {RERANKER_PATH}")
    print(f"🌐 Веб-интерфейс:      {WEB_DIR}")
    print("=" * 60)
    
    # Проверка моделей
    errors = validate_model_paths()
    if errors:
        print("\n⚠️ ОШИБКИ КОНФИГУРАЦИИ:")
        for err in errors:
            print(f"   ❌ {err}")
    else:
        print("\n✅ Все модели найдены")

