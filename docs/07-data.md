# 07. Загрузить Excel / Бэкап / Восстановление

## Загрузить Excel с данными

### Шаг 1. Подготовь Excel

Должен содержать минимум эти колонки:
- **code** — уникальный код (например `01.01.001`)
- **description** — описание (то, по чему ищут)

Опционально:
- **status** — статус (active/draft/deprecated)
- Любые другие колонки — будут импортированы как есть

### Шаг 2. Открой админку

http://localhost:8000/admin → авторизуйся

### Шаг 3. Создай коллекцию

1. На главной странице админки нажми **+ Создать коллекцию**
2. Введи имя (например `КСР 2024`)
3. Выбери размерность (должна совпадать с моделью эмбеддингов: 2560 для qwen3-4b)
4. Сохрани

### Шаг 4. Импортируй файл

1. Открой созданную коллекцию
2. Нажми **Импорт** (или перетащи Excel в окно)
3. Дождись завершения (в Flower видно: http://localhost:5555)

**Скорость:**
- Через OpenRouter: ~1500 строк за 5-10 минут
- Через LM Studio: зависит от видеокарты

## Бэкап

### Быстрый бэкап (только PostgreSQL)

```bash
make backup
```

Файл появится в `backups/ksr-YYYY-MM-DD-HHMMSS.sql.gz`.

### Бэкап всего (PostgreSQL + Qdrant)

```bash
make backup-full
```

Это создаст:
- `backups/pg-YYYY-MM-DD-HHMMSS.sql.gz` — все данные
- `backups/qdrant-YYYY-MM-DD-HHMMSS.tar.gz` — все векторы

### Вручную (если нужна гибкость)

```bash
# Только PostgreSQL
docker compose exec postgres pg_dump -U ksr ksr | gzip > backup.sql.gz

# Только Qdrant
docker compose exec qdrant tar czf - /qdrant/storage > qdrant-backup.tar.gz
```

## Восстановление

### Из быстрого бэкапа (только PostgreSQL)

```bash
make restore FILE=backups/ksr-2026-06-11-120000.sql.gz
```

⚠️ **Удалит текущие данные** и заменит на данные из бэкапа.

### Из полного бэкапа

Останови стек:
```bash
make down
```

Восстанови:
```bash
# PostgreSQL
docker compose up -d postgres
gunzip -c backups/pg-2026-06-11-120000.sql.gz | docker compose exec -T postgres psql -U ksr ksr

# Qdrant
docker compose up -d qdrant
docker compose exec -T qdrant tar xzf - -C / < qdrant-2026-06-11-120000.tar.gz

# Поднять всё
make up
```

## Автоматический бэкап по расписанию (Windows)

Создай файл `backup-daily.ps1`:
```powershell
cd "C:\Users\klim9\Yandex.Disk\02_Work\#Projects\04_DataScience\DS-25001-VectorSearch"
docker compose exec postgres pg_dump -U ksr ksr | Out-File "backups\auto-$(Get-Date -Format 'yyyy-MM-dd').sql" -Encoding utf8
```

Добавь в **Планировщик задач Windows** → триггер "Ежедневно в 3:00".

## Автоматический бэкап по расписанию (Linux/Mac)

```bash
# В crontab:
0 3 * * * cd /path/to/project && make backup
```

## Где хранить бэкапы

⚠️ **Не держи бэкапы только на своём ПК** — если он сгорит, потеряешь всё.

Рекомендации:
- Копируй в **облако** (Google Drive, Яндекс.Диск, Dropbox)
- Или настрой `rclone` / `rsync` на удалённый сервер

Простой скрипт синхронизации (PowerShell):
```powershell
robocopy "C:\Users\klim9\Yandex.Disk\02_Work\#Projects\04_DataScience\DS-25001-VectorSearch\backups" "Y:\Backups\KSR" /MIR
```

## Где живут данные

| Что | Где в Docker | Путь на твоём ПК |
|---|---|---|
| PostgreSQL | volume `pgdata` | (Docker volume) |
| Qdrant | volume `qdrant_data` | (Docker volume) |
| Redis | volume `redis_data` | (Docker volume) |
| Загруженные Excel | volume внутри контейнера | — (нужен отдельно) |
| Логи | container logs | `make logs` |

Чтобы посмотреть, где volume на хосте:
```bash
docker volume inspect ds-25001-vectorsearch_pgdata
```

## Удалить все данные (начать с нуля)

```bash
make prune
```

⛔️ **Безвозвратно.** Удалит все коллекции, материалы, фидбеки.
