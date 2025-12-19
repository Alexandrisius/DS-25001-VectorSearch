# План переписывания KSR Vector Search

## 1. Структура проекта

```
ksr-vector-search/
├── docker-compose.yml           # Оркестрация контейнеров
├── .env.example                  # Шаблон переменных окружения
├── .env                          # Локальные переменные (gitignore)
├── README.md
│
├── backend/                      # Python FastAPI приложение
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                  # Миграции PostgreSQL
│   │   ├── versions/
│   │   └── env.py
│   ├── alembic.ini
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, lifespan, middleware
│   │   ├── config.py             # Pydantic Settings
│   │   │
│   │   ├── api/                  # API роутеры (разбиты по доменам)
│   │   │   ├── __init__.py
│   │   │   ├── router.py         # Главный роутер (include всех)
│   │   │   ├── search.py         # /search, /match
│   │   │   ├── materials.py      # CRUD материалов
│   │   │   ├── folders.py        # CRUD папок, иерархия
│   │   │   ├── collections.py    # Управление коллекциями
│   │   │   ├── import_export.py  # Импорт CSV/Excel
│   │   │   ├── admin.py          # Авторизация, настройки
│   │   │   └── feedback.py       # Аналитика (copy/dislike)
│   │   │
│   │   ├── models/               # SQLAlchemy ORM модели
│   │   │   ├── __init__.py
│   │   │   ├── base.py           # Base, mixins (timestamps, uuid)
│   │   │   ├── folder.py         # Folder (иерархия)
│   │   │   ├── material.py       # Material
│   │   │   ├── material_folder.py # M2M связь
│   │   │   ├── custom_field.py   # Кастомные поля
│   │   │   ├── collection.py     # Метаданные коллекций
│   │   │   └── job.py            # Фоновые задачи
│   │   │
│   │   ├── schemas/              # Pydantic схемы (request/response)
│   │   │   ├── __init__.py
│   │   │   ├── material.py
│   │   │   ├── folder.py
│   │   │   ├── search.py
│   │   │   └── common.py
│   │   │
│   │   ├── services/             # Бизнес-логика
│   │   │   ├── __init__.py
│   │   │   ├── material_service.py
│   │   │   ├── folder_service.py
│   │   │   ├── search_service.py
│   │   │   ├── import_service.py
│   │   │   ├── sync_service.py   # Синхронизация PG <-> Qdrant
│   │   │   └── embedding_client.py # HTTP клиент к ML-серверу
│   │   │
│   │   ├── repositories/         # Слой доступа к данным
│   │   │   ├── __init__.py
│   │   │   ├── material_repo.py
│   │   │   ├── folder_repo.py
│   │   │   └── qdrant_repo.py
│   │   │
│   │   ├── db/                   # Подключения к БД
│   │   │   ├── __init__.py
│   │   │   ├── postgres.py       # AsyncSession factory
│   │   │   └── qdrant.py         # QdrantClient singleton
│   │   │
│   │   ├── core/                 # Общие утилиты
│   │   │   ├── __init__.py
│   │   │   ├── security.py       # JWT, password hashing
│   │   │   ├── exceptions.py     # Custom exceptions
│   │   │   └── dependencies.py   # FastAPI Depends
│   │   │
│   │   └── tasks/                # Фоновые задачи
│   │       ├── __init__.py
│   │       ├── runner.py         # BackgroundTasks runner
│   │       └── embedding_tasks.py
│   │
│   └── tests/
│       ├── conftest.py
│       ├── test_materials.py
│       └── test_search.py
│
├── frontend/                     # Статика (HTML/CSS/JS)
│   ├── index.html
│   ├── admin.html
│   └── static/
│       ├── css/
│       └── js/
│
├── ml-server/                    # Отдельный ML сервер (справочно)
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py               # /embed, /rerank endpoints
│       └── models.py
│
└── scripts/
    ├── migrate_data.py           # Миграция из старой структуры
    └── seed_data.py
```

## 2. Docker Compose архитектура

```yaml
services:
  postgres:     # PostgreSQL 16 + pgvector (на будущее)
  qdrant:       # Qdrant latest (отдельный контейнер)
  api:          # FastAPI backend
  # ml-server на отдельной машине (не в compose)
```

**Ключевые решения:**

- PostgreSQL = Source of Truth для метаданных
- Qdrant = векторный индекс (только postgres_id + vector + минимум payload)
- ML-сервер = внешний HTTP API (локальная сеть)

## 3. Схема данных PostgreSQL

Основные таблицы согласно вашей архитектуре:

| Таблица | Назначение |

|---------|------------|

| `collections` | Метаданные коллекций (thresholds, visible, locked) |

| `folders` | Иерархия категорий (parent_id, full_path cache, materials_count cache) |

| `materials` | Материалы (code, name, description, qdrant_point_id) |

| `material_folders` | M2M связь материал-папки (position) |

| `custom_field_definitions` | Определения кастомных полей |

| `material_custom_fields` | Значения кастомных полей |

| `background_jobs` | Очередь фоновых задач |

| `feedback_events` | Аналитика (copy, dislike) |

**Триггеры PostgreSQL:**

- `trg_folders_update_full_path` - автообновление full_path при изменении name/parent_id
- `trg_material_folders_update_count` - обновление materials_count в folders

## 4. Интеграция с ML-сервером

```
[API Backend] --HTTP--> [ML Server на другой машине]
     |                         |
     |   POST /embed           |  Qwen3-Embedding-4B
     |   POST /rerank          |  BGE-M3 / Jina-v3
     |   GET /health           |
```

`embedding_client.py` - httpx AsyncClient с retry, timeout, connection pooling.

## 5. Ключевые API эндпоинты

| Группа | Эндпоинты |

|--------|-----------|

| Search | `POST /search`, `POST /hierarchy/{collection}/search` |

| Materials | `GET/POST/PUT/DELETE /materials/{id}` |

| Folders | `GET/POST/PUT/DELETE /folders/{id}`, `GET /folders/tree` |

| Collections | `GET/POST/PUT/DELETE /collections/{name}` |

| Import | `POST /import/csv`, `GET /import/jobs/{id}` |

| Admin | `POST /auth/login`, `GET /admin/stats` |

| Feedback | `POST /feedback/copy`, `POST /feedback/dislike` |

## 6. Алгоритм синхронизации PostgreSQL <-> Qdrant

При изменении материала/папки:

1. Обновление PostgreSQL (транзакция)
2. Получение нового context_description
3. HTTP запрос к ML-серверу за эмбеддингом
4. Upsert в Qdrant по qdrant_point_id
5. Фоновая задача для batch операций (переименование папки)

## 7. План миграции данных

1. Экспорт текущих данных из Qdrant в JSON
2. Парсинг path_level_N -> создание записей folders
3. Создание materials и связей material_folders
4. Регенерация эмбеддингов (batch через ML-сервер)
5. Загрузка в новый Qdrant

## 8. Этапы реализации

| Этап | Описание | Файлы |

|------|----------|-------|

| 1 | Docker Compose + базовая структура | `docker-compose.yml`, структура папок |

| 2 | PostgreSQL модели + миграции | `models/`, `alembic/` |

| 3 | Qdrant репозиторий + embedding client | `repositories/qdrant_repo.py`, `services/embedding_client.py` |

| 4 | CRUD материалов и папок | `api/materials.py`, `api/folders.py`, `services/` |

| 5 | Поиск (Stage 1 + Stage 2) | `api/search.py`, `services/search_service.py` |

| 6 | Синхронизация PG <-> Qdrant | `services/sync_service.py` |

| 7 | Импорт CSV/Excel | `api/import_export.py`, `services/import_service.py` |

| 8 | Авторизация + админка | `api/admin.py`, `core/security.py` |

| 9 | Frontend (перенос + адаптация) | `frontend/` |

| 10 | Миграция данных + тесты | `scripts/migrate_data.py`, `tests/` |