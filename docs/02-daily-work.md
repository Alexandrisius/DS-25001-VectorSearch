# 02. Ежедневная работа

Сайт работает в Docker. Утром поднял → вечером выключил. Всё.

## Запустить сайт

```bash
make up
```

Подождать 30 секунд. Открыть http://localhost:8000

## Остановить сайт

```bash
make down
```

Данные сохраняются. При следующем `make up` всё на месте.

## Посмотреть логи (если что-то не работает)

```bash
make logs              # все сервисы
make logs-api          # только API
make logs-celery       # только фоновые задачи
```

`Ctrl+C` чтобы выйти.

## Зашёл в админку и нажал "Сохранить" — а изменений нет

Скорее всего, ты не авторизовался. Введи пароль `admin` на странице входа.

## Поменял UI (HTML/JS/CSS) — что делать?

**Ничего.** UI подключен напрямую в Docker через volume (`./web:/app/web:ro`).

Просто сохрани файл и **обнови вкладку в браузере** (`Ctrl+F5` — без кеша).

Примеры UI файлов:
- `web/index.html` — главная страница поиска
- `web/admin.html` — админка
- `web/static/js/app.js` — логика поиска
- `web/static/js/admin.js` — логика админки
- `web/static/css/admin.css` — стили админки

**Не нужен** рестарт контейнеров, не нужно пересобирать образ.

## Поменял что-то в Python (`api/app/...`) — что делать?

Пересобрать и перезапустить API:

```bash
make rebuild-api
```

Это займёт ~30 секунд (uv ставит зависимости, потом Docker перезапускает 2 контейнера: `ksr_api` и `ksr_celery_worker`).

Подробнее — [03-update-code.md](03-update-code.md).

## Поменял зависимости (`pyproject.toml`) — что делать?

То же самое:

```bash
make rebuild-api
```

## Что-то глючит — как перезапустить "с нуля"?

```bash
make restart           # мягкий перезапуск
# или
make rebuild           # полная пересборка всех образов
```

## Хочу зайти внутрь контейнера (отладка)

```bash
make shell-api
```

Окажешься в bash внутри контейнера API. Можно смотреть файлы, гонять Python.

Чтобы выйти: `exit`

## Хочу удалить ВСЕ данные и начать с нуля

```bash
make prune
```

Удалит тома (volume) — БД, Qdrant, Redis. **Безвозвратно.**

## Чек-лист "сайт живой"

```bash
# 1. Health check
curl http://localhost:8000/health
# Ожидаем: {"status":"ok","version":"2.0.0"}

# 2. Контейнеры запущены
docker ps
# Должно быть 6 контейнеров ksr_*
```

Если `/health` не отвечает — смотри `make logs-api`.

## Аналитика поиска (кто что искал, как быстро)

Каждый `/match` пишется в Postgres (`search_events`) + одна строка
JSON-лога. Смотреть можно в админке и в БД.

### В админке

http://localhost:8000/admin → таб **«Аналитика»**.

4 KPI-карточки (поисков, zero-result %, p95/p50 латентность, активные
сотрудники) + 3 таблицы (последние поиски, zero-result запросы,
медленные > 2с). Автообновление каждые 30 секунд.

### Через SQL (make shell-postgres)

```bash
# KPI за сегодня
make shell-postgres -c "SELECT * FROM v_search_stats_daily ORDER BY day DESC LIMIT 7;"

# Топ-20 самых частых запросов за 90 дней
make shell-postgres -c "SELECT * FROM v_top_queries LIMIT 20;"

# Контент-гэпы: что искали, но не нашли (за 90 дней)
make shell-postgres -c "SELECT * FROM v_zero_result_queries LIMIT 20;"

# Кто искал "бетон м300" за неделю
make shell-postgres -c "SELECT ts, user_ip, total_ms, candidates_count FROM search_events WHERE query ILIKE '%бетон м300%' ORDER BY ts DESC LIMIT 20;"

# Таймлайн одного сотрудника (по IP)
make shell-postgres -c "SELECT * FROM search_events WHERE user_ip = '1.2.3.4' ORDER BY ts DESC LIMIT 50;"
```

### В Docker-логах (структурированный JSON)

В `.env` выставить `LOG_FORMAT=json` (по умолчанию `text`).

```bash
# Все события search_completed
make logs-api 2>&1 | grep "search_completed" | jq .

# Медленные > 3с
make logs-api 2>&1 | jq 'select(.event=="search_completed" and .total_ms>3000)'

# Что делал конкретный IP
make logs-api 2>&1 | jq 'select(.user_ip=="1.2.3.4")'
```

### Что значит каждая метрика

- **Zero-result rate** — доля поисков без результатов. < 3% зелёный,
  3-10% жёлтый, > 10% красный (пороги из Meilisearch/AWS Kendra).
- **p50/p95 total_ms** — медиана и 95-й перцентиль полного времени
  поиска. Если p95 > 5с — реранкер тормозит, пора менять провайдера.
- **p95 rerank_ms** — отдельно по реранкеру (самая тяжёлая стадия).
  Должно быть < 3с на обычных запросах.
- **Копирования/дизлайки после поиска** — в UI таб «Последние поиски»
  в колонке «Действия»: 📋 N 👍/👎 N.
