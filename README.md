# KSR Vector Search v2

Семантический поиск по КСР (Классификатор Строительных Ресурсов) с двухэтапным retrieval (vector + rerank) и интеграцией с OpenRouter API.

> **Стек:** Python 3.12 · FastAPI · PostgreSQL 16 · Qdrant · Redis · Celery · Docker

---

## 📖 Документация

**`docs/`** — пошаговые инструкции для обычной работы (без жаргона):

- **[docs/01-first-run.md](docs/01-first-run.md)** — первый запуск сайта
- **[docs/02-daily-work.md](docs/02-daily-work.md)** — ежедневная работа (запустить/остановить/обновить UI)
- **[docs/04-api-key.md](docs/04-api-key.md)** — ввести API ключ OpenRouter
- **[docs/05-lm-studio.md](docs/05-lm-studio.md)** — подключить LM Studio
- **[docs/06-tunnel.md](docs/06-tunnel.md)** — открыть сайт друзьям
- **[docs/07-data.md](docs/07-data.md)** — загрузить Excel / бэкап
- **[docs/08-deploy-vps.md](docs/08-deploy-vps.md)** — развернуть на VPS

Или **набери `make help`** — там все команды с описаниями.

**Если у тебя Windows и нет `make`** — используй `.\make.ps1 help`.

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
├── docker-compose.yml    # 6 сервисов + опциональный cloudflared
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

## 🤖 LLM API: OpenRouter + LM Studio

Все настройки моделей и API ключей задаются **через админку** (`http://localhost:8000/admin` → Настройки → LLM API).

### OpenRouter (по умолчанию)
- Получите API ключ на [openrouter.ai/keys](https://openrouter.ai/keys)
- Вставьте в поле "API Key" в админке
- Выберите модели:
  - **Эмбеддинги:** `qwen/qwen3-embedding-4b` (2560d), `qwen/qwen3-embedding-8b` (4096d), `openai/text-embedding-3-small/large`
  - **Реранкер (cross-encoder):** `cohere/rerank-4-pro` или `cohere/rerank-4-fast`

### LM Studio (OpenAI-совместимый endpoint)
Можно подключить локально запущенный LM Studio, Ollama или vLLM:

1. Запустите LM Studio и включите локальный сервер (по умолчанию `http://localhost:1234`)
2. Загрузите модели (например embedding + reranker)
3. В админке:
   - **API Key:** любое значение (например `lm-studio`) — игнорируется
   - **Base URL:** `http://host.docker.internal:1234/v1`
   - **Модель эмбеддингов:** имя модели из LM Studio (например `text-embedding-nomic-embed-text-v1.5`)
   - **Модель реранкера:** имя reranker-модели (если есть)

> `host.docker.internal` — специальный DNS, который Docker Desktop пробрасывает на хост-машину (только Windows/macOS).

---

## 🌐 Cloudflare Tunnel (одной командой)

После первоначальной настройки в Cloudflare Dashboard, туннель поднимается **вместе со всем стеком** одной командой.

### Первоначальная настройка (один раз)

1. Зайдите в [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) → **Networks** → **Tunnels** → **Create a tunnel**
2. Тип: **Cloudflared** → имя: `ksrmatch` (или любое)
3. Скопируйте **TUNNEL_TOKEN** (длинная строка)
4. На вкладке **Public Hostname** добавьте:
   - Subdomain: `@` (или пусто) → Domain: `ksrmatch.online`
   - Service: `http://api:8000`

### Запуск

```bash
# Добавьте токен в .env
echo "TUNNEL_TOKEN=eyJhIjoixxxxxxxxxxxxx..." >> .env

# Поднимите весь стек (включая cloudflared)
docker compose --profile tunnel up -d
```

Или используйте отдельный compose-файл (только cloudflared, основной стек уже работает):

```bash
docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d
```

> Если `TUNNEL_TOKEN` пустой, cloudflared не поднимется (через `profiles: ["tunnel"]`).

### Проверка

```bash
docker compose logs cloudflared
# Должно быть: "Connection established" / "Registered tunnel connection"
```

После этого сайт доступен по `https://ksrmatch.online` без проброса портов на роутере.

---

## ⚠️ Известные проблемы / TODO

- [ ] Исторические JSONL-фидбеки НЕ мигрированы (оставлены в `feature-qdrant` как архив)
- [ ] BM25 хранится in-memory (для 150k записей — OK, при 1M+ переходить на Qdrant sparse)
- [ ] Нет UI для просмотра feedback_events (только SQL)

---

## 📜 Лицензия

MIT
