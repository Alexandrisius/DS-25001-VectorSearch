# 03. Обновить Python код

Когда меняешь что-то в `api/app/...` или `api/alembic/...`, нужно пересобрать API образ.

## Зачем

Python код "запекается" в Docker-образ при сборке. Когда ты правишь файл в редакторе, контейнер об этом не знает. Нужно пересобрать.

## Команда

```bash
make rebuild-api
```

Это:
1. Пересобирает образ API (`docker compose build api`)
2. Перезапускает `ksr_api` и `ksr_celery_worker` (`docker compose up -d api celery_worker`)

Время: ~30 секунд (зависит от того, сколько pip-пакетов кешировано).

## Если изменил миграцию Alembic

После `make rebuild-api` нужно применить миграции:

```bash
make migrate
```

## Если изменил `pyproject.toml` (добавил библиотеку)

Та же команда:

```bash
make rebuild-api
make migrate   # на всякий случай
```

## Частые ошибки

### `make rebuild-api` падает на pip install

Скорее всего, опечатка в `pyproject.toml` или конфликт версий. Смотри вывод:

```bash
make rebuild-api 2>&1 | Select-String "ERROR|error:"
```

### После rebuild сайт не поднимается

```bash
make logs-api | Select-String "Error" -CaseSensitive:$false
```

### Хочу откатить изменения

```bash
git checkout api/app/services/embedding_service.py
make rebuild-api
```

## Что НЕ требует пересборки

- **HTML/JS/CSS** в `web/` — обновляй вкладку браузера
- **`.env`** — `make restart` (но НЕ rebuild)
- **Данные в БД** — ничего, они в volume

## Под капотом (если интересно)

```bash
# Вручную (что делает make rebuild-api):
docker compose build api                          # собрать образ
docker compose up -d api celery_worker            # перезапустить контейнеры
```

`api/Dockerfile` — multi-stage: сначала `uv` ставит пакеты, потом копируется в runtime-образ.
`./api:/app` смонтирован в контейнер **только для чтения**, поэтому правки в файлах не подхватываются автоматически — нужна пересборка.
