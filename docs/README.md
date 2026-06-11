# Документация KSR Vector Search v2

Здесь собраны пошаговые инструкции для **обычной работы** с сайтом.
Без жаргона, без лишних деталей. Просто делай что написано.

---

## С чего начать

1. **[01-first-run.md](01-first-run.md)** — Первый запуск сайта на своём ПК
2. **[02-daily-work.md](02-daily-work.md)** — Ежедневная работа: запустить/остановить, проверить
3. **[04-api-key.md](04-api-key.md)** — Ввести API ключ OpenRouter
4. **[06-tunnel.md](06-tunnel.md)** — Открыть сайт для друзей через Cloudflare

## Кейсы (когда что-то сломалось / хочется нового)

| Что хочу сделать | Читай |
|---|---|
| Поменять UI (HTML, JS, CSS) | [02-daily-work.md](02-daily-work.md) — раздел "Поменял UI" |
| Поменять Python код | [03-update-code.md](03-update-code.md) |
| Ввести / поменять API ключ OpenRouter | [04-api-key.md](04-api-key.md) |
| Подключить LM Studio вместо OpenRouter | [05-lm-studio.md](05-lm-studio.md) |
| Загрузить Excel с данными | [07-data.md](07-data.md) — раздел "Загрузить Excel" |
| Сделать бэкап данных | [07-data.md](07-data.md) — раздел "Бэкап" |
| Открыть сайт друзьям по нормальной ссылке | [06-tunnel.md](06-tunnel.md) |
| Развернуть на VPS (когда надоест дома) | [08-deploy-vps.md](08-deploy-vps.md) |
| Сменить пароль админки / токены / секреты | [09-security-secrets.md](09-security-secrets.md) |

## Справочник команд

Все действия — это `make команда`. Запускай в терминале из корня проекта.

| Команда | Что делает |
|---|---|
| `make up` | Запустить весь стек (PostgreSQL, Qdrant, API, Celery) |
| `make down` | Остановить стек |
| `make restart` | Перезапустить (down + up) |
| `make logs` | Смотреть логи всех сервисов |
| `make logs-api` | Логи только API |
| `make shell-api` | Войти внутрь контейнера API (отладка) |
| `make rebuild-api` | **Пересобрать API** (нужно после правок Python кода) |
| `make migrate` | Применить миграции БД |
| `make backup` | Дамп PostgreSQL в `backups/` |
| `make tunnel-up` | Запустить Cloudflare Tunnel (открыть сайт друзьям) |
| `make tunnel-down` | Остановить Cloudflare Tunnel |
| `make password NEW=xxx` | Сменить пароль админки (и пересобрать API) |
| `make open-admin` | Открыть админку в браузере |
| `make open-site` | Открыть сайт в браузере |

## Куда жаловаться

Если что-то не работает:
1. `make logs` — смотри последние строки
2. `make logs-api | Select-String "Error"` — найди ошибки
3. Напиши в чат — пришли эти логи
