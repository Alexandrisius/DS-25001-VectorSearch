# 01. Первый запуск сайта

Это **единожды**. Дальше просто `make up` / `make down`.

## Шаг 1. Проверь что Docker установлен

```bash
docker --version
```

Если команда не найдена — скачай [Docker Desktop](https://www.docker.com/products/docker-desktop/) и установи. На Windows он попросит перезагрузку.

## Шаг 2. Скопируй файл с секретами

```bash
# Из корня проекта:
cp .env.example .env
```

(На Windows PowerShell: `Copy-Item .env.example .env`)

Файл `.env` уже содержит все нужные ключи для **dev-режима** (пароль `admin`, тестовые JWT и Fernet ключи). Для своего ПК этого достаточно. На VPS — нужно сгенерировать свои (см. `08-deploy-vps.md`).

## Шаг 3. Подними весь стек

```bash
make up
```

Подожди ~30 секунд. Должно появиться:

```
✔ Container ksr_postgres       Healthy
✔ Container ksr_qdrant         Started
✔ Container ksr_redis          Healthy
✔ Container ksr_api            Started
✔ Container ksr_celery_worker  Started
✔ Container ksr_flower         Started
```

## Шаг 4. Примени миграции (создать таблицы в БД)

```bash
make migrate
```

В ответе должно быть:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, initial schema
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002_add_base_url, add base_url to api_providers
```

## Шаг 5. Открой сайт

```bash
make open-site
```

Или вручную: http://localhost:8000

Должна открыться страница поиска.

## Шаг 6. Зайди в админку

```bash
make open-admin
```

Или вручную: http://localhost:8000/admin

Логин: **admin**
Пароль: **admin** (задан в `.env`)

## Что внутри стека

После `make up` работают 6 контейнеров:

| Контейнер | Что делает | Адрес |
|---|---|---|
| `ksr_postgres` | Хранит все данные (материалы, настройки, фидбек) | localhost:5432 |
| `ksr_qdrant` | Хранит векторы (эмбеддинги) для поиска | localhost:6333 |
| `ksr_redis` | Кеш + очередь задач Celery | localhost:6379 |
| `ksr_api` | Сам сайт (FastAPI) | **localhost:8000** |
| `ksr_celery_worker` | Фоновые задачи (импорт Excel, пересчёт папок) | — |
| `ksr_flower` | Веб-интерфейс для Celery (мониторинг задач) | localhost:5555 (admin/admin) |

## Готово

Переходи к **[04-api-key.md](04-api-key.md)** — введи свой API ключ OpenRouter, чтобы работал поиск.
