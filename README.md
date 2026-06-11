# KSR Vector Search v2

Семантический поиск по КСР (Классификатор Строительных Ресурсов) с двухэтапным retrieval (vector + rerank) и интеграцией с OpenRouter API.

> **Стек:** Python 3.12 · FastAPI · PostgreSQL 16 · Qdrant · Redis · Celery · Docker

---

## 🚀 Быстрый старт (локально)

```bash
# 1. Скопировать .env.example в .env и заполнить (для dev подойдёт дефолтный .env)
cp .env.example .env

# 2. Поднять весь стек
make up

# 3. Применить миграции
make migrate

# 4. Открыть UI
open http://localhost:8000
```

**Сервисы после `make up`:**
- API: http://localhost:8000
- Админка: http://localhost:8000/admin
- API docs: http://localhost:8000/docs
- Flower (Celery UI): http://localhost:5555 (admin/admin)
- Qdrant: http://localhost:6333

---

## 📁 Структура

```
.
├── api/                  # Backend (FastAPI + Celery)
│   ├── app/
│   │   ├── api/          # Роутеры (по доменам)
│   │   ├── core/         # Безопасность, исключения, логирование
│   │   ├── db/           # Postgres, Qdrant, Redis
│   │   ├── models/       # SQLAlchemy ORM
│   │   ├── schemas/      # Pydantic v2
│   │   ├── services/     # Бизнес-логика
│   │   ├── repositories/ # Доступ к данным
│   │   ├── workers/      # Celery задачи
│   │   ├── utils/        # Утилиты (path_levels, cleaning, excel)
│   │   ├── config.py     # Настройки (Pydantic v2)
│   │   ├── deps.py       # FastAPI Depends
│   │   └── main.py       # FastAPI app
│   ├── alembic/          # Миграции
│   ├── pyproject.toml
│   └── Dockerfile
├── web/                  # Frontend (HTML/CSS/JS, as-is)
├── deploy/               # Скрипты деплоя
├── docker-compose.yml    # 6 сервисов
├── .env.example
├── Makefile
└── README.md
```

---

## 🔐 Безопасность

- **Пароль админа** хранится как bcrypt-хеш в env (`ADMIN_PASSWORD_HASH`)
- **API ключ OpenRouter** шифруется Fernet и хранится в БД (`api_providers.api_key_encrypted`)
- **JWT** с HS256, 8 часов жизни, refresh через повторный логин
- **Rate-limit** на вход: 5 попыток, блокировка IP на 5 минут

> ⚠️ **Сгенерируйте свои секреты перед прод-деплоем:**
> ```bash
> # bcrypt хеш пароля
> python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"
>
> # JWT secret
> python -c "import secrets; print(secrets.token_urlsafe(32))"
>
> # Fernet key для OpenRouter API
> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (UI: index.html + admin.html)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI (api)                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐    │
│  │ /match      │  │ /admin/*     │  │ /hierarchy/*     │    │
│  │ Search      │  │ CRUD + auth  │  │ Catalog tree     │    │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘    │
│         │                │                   │              │
│  ┌──────▼────────────────▼───────────────────▼─────────┐   │
│  │ Services: Search, Material, Folder, Import, ...     │   │
│  └──┬──────────┬──────────┬──────────┬─────────────┬───┘   │
│     │          │          │          │             │       │
│  ┌──▼──┐   ┌───▼───┐  ┌───▼────┐ ┌───▼────┐  ┌─────▼─────┐ │
│  │Post-│   │Qdrant │  │Redis   │ │Celery  │  │OpenRouter │ │
│  │gres │   │       │  │(cache) │ │worker  │  │(embed+rer)│ │
│  └─────┘   └───────┘  └────────┘ └────────┘  └───────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Основные команды

| Команда | Описание |
|---------|----------|
| `make up` | Поднять весь стек |
| `make down` | Остановить стек |
| `make logs` | Логи всех сервисов |
| `make logs-api` | Логи API |
| `make migrate` | Применить миграции |
| `make revision msg=...` | Создать новую миграцию |
| `make shell-api` | Войти в контейнер API |
| `make test` | Запустить тесты |
| `make lint` | Ruff check |
| `make backup` | Дамп Postgres |
| `make restore FILE=...` | Восстановить из дампа |
| `make prune` | ⚠️ Удалить ВСЕ данные |

---

## 🚀 Деплой на VPS

```bash
# На VPS:
git clone <repo>
cd DS-25001-VectorSearch
cp .env.example .env
# Заполнить .env (POSTGRES_PASSWORD, JWT_SECRET_KEY, ENCRYPTION_KEY, ADMIN_PASSWORD_HASH)
make up
make migrate
```

Опционально — настроить nginx + Let's Encrypt для HTTPS (см. `deploy/nginx/`).

---

## ⚠️ Известные проблемы / TODO

- [ ] Исторические JSONL-фидбеки НЕ мигрированы (оставлены в `feature-qdrant` как архив)
- [ ] BM25 хранится in-memory (для 150k записей — OK, при 1M+ переходить на Qdrant sparse)
- [ ] Нет UI для просмотра feedback_events (только SQL)

---

## 📜 Лицензия

MIT
