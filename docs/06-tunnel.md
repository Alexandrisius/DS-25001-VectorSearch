# 06. Открыть сайт друзьям (Cloudflare Tunnel)

По умолчанию сайт доступен только тебе: `http://localhost:8000`.
Чтобы друзья открыли по нормальной ссылке (например `https://ksrmatch.online`) — нужен туннель.

## Что такое Cloudflare Tunnel

Бесплатный сервис. Ставишь утилиту `cloudflared`, она пробрасывает твой localhost в интернет через защищённое соединение. Не нужно пробрасывать порты на роутере, не нужен белый IP.

## Одноразовая настройка (10 минут)

### Шаг 1. Создай аккаунт Cloudflare

Если нет: https://dash.cloudflare.com/sign-up

### Шаг 2. Добавь свой домен (если ещё не добавлен)

Cloudflare → **Add a site** → введи домен (например `ksrmatch.online`) → выбери бесплатный план.

Cloudflare даст 2 nameserver'а. Пропиши их у регистратора домена (где покупал).

⏳ Жди до 24 часов, пока домен пропишется.

### Шаг 3. Создай туннель

Cloudflare Dashboard → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel**

- Тип: **Cloudflared**
- Имя: `ksrmatch` (любое)
- Скопируй **TUNNEL_TOKEN** (длинная строка вида `eyJhIjoixxxxxxx...`)

### Шаг 4. Настрой Public Hostname

На той же странице туннеля → вкладка **Public Hostname** → **Add a public hostname**:

| Поле | Значение |
|---|---|
| Subdomain | (пусто) |
| Domain | ksrmatch.online |
| Service | `http://api:8000` |

**Важно:** Service должен быть `http://api:8000` (имя Docker-сервиса), а не localhost!

### Шаг 5. Запусти туннель

Открой `.env` в корне проекта и добавь строку:

```
TUNNEL_TOKEN=eyJhIjoixxxxxxxxxxxxxxxx...
```

Запусти:

```bash
make tunnel-up
```

Или напрямую:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d cloudflared
```

Через ~30 секунд твой сайт будет доступен по `https://ksrmatch.online` 🎉

## ⚠️ Gotcha: миграция `localhost` → `api` (после Start migration)

Если у тебя в Cloudflare Dashboard жмёшь "Start migration" на **уже существующем**
локально-сконфигурированном туннеле (созданном через `cloudflared tunnel create`),
Cloudflare **мигрирует твои ingress rules как есть** — включая старый service URL.

**Симптом:** туннель в статусе HEALTHY, логи показывают
`INF Connection established`, но сайт возвращает `502 Bad Gateway` или
`Unable to reach the origin service: dial tcp [::1]:8000: connection refused`.

**Причина:** старый config.yml имел `service: http://localhost:8000`.
Cloudflared контейнер НЕ в `network_mode: host` (он в Docker сети `ksr_net`),
поэтому `localhost:8000` внутри контейнера = сам cloudflared, а не твой API.

**Фикс (1 минута):**
1. Zero Trust → Networks → Tunnels → `ksr-tunnel` → вкладка **"Published application routes"**
2. Жми **Edit** на правиле `ksrmatch.online`
3. Service URL: `localhost:8000` → **`api:8000`**
4. Path: очисти (если был `^/blog` или другой regex из старого config)
5. **Save** — cloudflared подхватит за ~10 сек

**Проверить:**
```bash
make tunnel-logs
# Должно появиться: "Updated to new configuration ... service: http://api:8000"
# И исчезнуть "ERR Unable to reach the origin service"

curl -s https://ksrmatch.online/health
# {"status":"ok","version":"2.0.0"}
```

**Не путай вкладки:**
- "Published application routes" — для **публичных** сайтов (твой случай)
- "Hostname routes" (beta) — для **приватных** сетей через Cloudflare One Client
  (требует WARP на стороне клиента, для обычного сайта не подходит)

## Проверить что туннель работает

```bash
make tunnel-logs
```

Должно быть:
```
INF Connection established connIndex=0 ...
INF Registered tunnel connection ...
```

Или проверь через браузер: открой `https://ksrmatch.online` — должен загрузиться твой сайт.

## Остановить туннель

```bash
make tunnel-down
```

Или:

```bash
docker compose --profile tunnel down
```

Сайт перестанет быть доступен из интернета (но локально на http://localhost:8000 продолжит работать).

## Управление

| Команда | Что делает |
|---|---|
| `make tunnel-up` | Запустить cloudflared (если TUNNEL_TOKEN в .env) |
| `make tunnel-down` | Остановить cloudflared |
| `make tunnel-logs` | Смотреть логи туннеля |

## Что делать когда перезагружаешь ПК

```bash
make up           # поднять весь стек
make tunnel-up    # поднять туннель
```

Всё. Сайт снова доступен друзьям.

## Альтернатива: Quick Tunnel (без домена, для теста)

Если не хочешь заморачиваться с доменом и Dashboard, можно за 5 секунд получить ссылку `*.trycloudflare.com`:

```bash
docker run --rm -it cloudflare/cloudflared:latest tunnel --no-autoupdate --url http://host.docker.internal:8000
```

В выводе будет строка `https://random-word-random.trycloudflare.com` — отправляй друзьям.

⚠️ **Минус:** ссылка меняется при каждом запуске, нет HTTPS-сертификата, нестабильно. Для серьёзного использования делай named tunnel (выше).

## Проблемы

### "connection refused" в логах cloudflared
- Убедись, что API контейнер работает: `docker ps | Select-String "ksr_api"`
- Убедись, что `http://localhost:8000/health` возвращает `{"status":"ok"}`

### Сайт открывается, но долго грузится
- Это нормально для туннеля — трафик идёт через Cloudflare. На прямом VPS будет быстрее.

### `host.docker.internal` не работает (Linux)
- На Linux `host.docker.internal` не работает "из коробки". Добавь в `docker-compose.yml`:
  ```yaml
  cloudflared:
    extra_hosts:
      - "host.docker.internal:host-gateway"
  ```
  Или используй `network_mode: host`.

## Безопасность

- Cloudflare Tunnel — это **безопасный** способ: твой ПК не торчит в интернет напрямую
- Cloudflare автоматически выдаёт HTTPS-сертификат
- Можно добавить Cloudflare Access (Zero Trust) — требовать логин перед доступом к админке
