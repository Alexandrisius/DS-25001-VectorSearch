# Деплой на hoster.by (VPS + Docker + Portainer)

Полный пошаговый гайд для развёртывания KSR Vector Search v2 на hoster.by.

---

## 📋 Что нужно от hoster.by

| Параметр | Минимум | Рекомендую |
|----------|---------|------------|
| **Тариф** | VPS 2 vCPU / 2 GB RAM / 20 GB SSD | VPS 2 vCPU / 4 GB RAM / 40 GB SSD |
| **ОС** | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| **Docker** | Предустановленный (Portainer) | Предустановленный |
| **Порт** | Открыть TCP 8000 (или через Cloudflare Tunnel) | — |
| **DNS** | A-record → IP (если без Cloudflare Tunnel) | Cloudflare Tunnel (без открытия портов) |

---

## 🚀 Способ 1: Portainer (рекомендую — самый простой)

### Шаг 1. Создайте VPS
В hoster.by → Hoster Cloud → Создать сервер → шаблон **"VPS + Portainer"** (Ubuntu 22.04+, 2 GB RAM).

После создания откройте Portainer:
- URL: `https://<IP_VPS>:9443`
- Создайте admin-пользователя при первом входе
- Выберите **"Get Started"** → **"Local"** environment

### Шаг 2. Создайте секреты

В Portainer → **Stacks** → **Add stack** → **Git repository**:

| Поле | Значение |
|------|----------|
| Name | `ksr` |
| Repository URL | `https://github.com/Alexandrisius/DS-25001-VectorSearch.git` |
| Repository reference | `refs/heads/refactor/v2-clean-architecture` |
| Compose path | `docker-compose.yml` |

**НЕ НАЖИМАЙТЕ "Deploy"!** Сначала задайте env-переменные.

### Шаг 3. Env-переменные (Portainer Web Editor)

В разделе **"Environment variables"** вставьте:

```env
POSTGRES_DB=ksr
POSTGRES_USER=ksr
POSTGRES_PASSWORD=СГЕНЕРИРОВАТЬ_СИЛЬНЫЙ_ПАРОЛЬ
ADMIN_PASSWORD_HASH=СГЕНЕРИРОВАТЬ_BCRYPT
JWT_SECRET_KEY=СГЕНЕРИРОВАТЬ_SECURE_TOKEN
ENCRYPTION_KEY=СГЕНЕРИРОВАТЬ_FERNET_KEY
SERVER_PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=https://ksrmatch.online
```

### Шаг 4. Генерация секретов

Откройте **Portainer → Containers → portainer → Console** (или через SSH):

```bash
# Установите Python + bcrypt
apt update && apt install -y python3-pip
pip3 install bcrypt cryptography

# Генерация секретов:
python3 -c "import bcrypt; print('POSTGRES_PASSWORD=', bcrypt.hashpw(b'CHANGE_ME', bcrypt.gensalt()).decode())"
python3 -c "import secrets; print('JWT_SECRET_KEY=', secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=', Fernet.generate_key().decode())"

# Bcrypt-хеш для админа (вместо примера — замените YOUR_PASSWORD):
python3 -c "import bcrypt; print('ADMIN_PASSWORD_HASH=', bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt(rounds=12)).decode())"
```

Скопируйте вывод каждой команды в Portainer.

### Шаг 5. Deploy

Нажмите **"Deploy the stack"** — Portainer:
1. Склонирует репо (ветка `refactor/v2-clean-architecture`)
2. Прочитает `docker-compose.yml`
3. Подставит env-переменные
4. Запустит 6 контейнеров (api, postgres, qdrant, redis, celery_worker, flower)

⏱️ Ожидание: 3-5 минут (сборка образа api + скачивание).

### Шаг 6. Применить миграции БД

**Portainer → Containers → ksr_api → Console → sh**

Внутри контейнера:
```bash
alembic upgrade head
# Должно создать таблицы в PostgreSQL
```

Или через SSH на VPS:
```bash
cd ~/stacks/ksr
docker compose exec api alembic upgrade head
```

### Шаг 7. Проверить

```bash
# Из SSH:
curl http://localhost:8000/health
# {"status":"ok","version":"2.0.0"}

# Через Portainer → Containers:
# - ksr_api → Logs (нет ошибок)
# - ksr_postgres → Status (healthy)
# - ksr_qdrant → Status (healthy)
# - ksr_redis → Status (healthy)
```

Открыть в браузере:
- `http://<IP_VPS>:8000` — UI поиска
- `http://<IP_VPS>:8000/admin` — админка (ваш пароль)
- `http://<IP_VPS>:8000/docs` — Swagger API

### Шаг 8. Открыть порт 8000

**В панели hoster.by:**
- Найдите ваш VPS → **Firewall** / **Сетевые настройки** / **Security Groups**
- Добавьте правило: **Inbound TCP 8000** (или 0.0.0.0/0 для публичного доступа)
- Если такого нет — попросите поддержку hoster.by открыть порт

### Шаг 9. Подключить домен `ksrmatch.online`

**Вариант A: Cloudflare DNS (proxy orange cloud):**
1. Cloudflare → DNS → Add A-record:
   - Name: `ksrmatch.online`
   - IPv4: `<IP_VPS>`
   - Proxy: **Proxied** (оранжевое облако)
2. SSL/TLS → Full mode
3. Готово! https://ksrmatch.online

**Вариант B: Cloudflare Tunnel (без открытия 8000):**
1. Cloudflare → Zero Trust → Networks → Tunnels → Create
2. Тип: **Cloudflared**
3. Public hostname: `ksrmatch.online` → `http://api:8000`
4. Скопируйте токен
5. Добавьте в `docker-compose.yml`:
   ```yaml
   cloudflared:
     image: cloudflare/cloudflared:latest
     command: tunnel run
     environment:
       TUNNEL_TOKEN: <ваш-токен>
     depends_on: [api]
     restart: unless-stopped
   ```
6. `docker compose up -d cloudflared`

### Шаг 10. Ввести OpenRouter API ключ

1. Откройте `https://ksrmatch.online/admin`
2. Settings → **OpenRouter** → включите + вставьте новый API ключ (создайте его в [openrouter.ai/keys](https://openrouter.ai/keys))
3. **СОВЕТ:** отзовите старый утёкший ключ в OpenRouter
4. Ключ зашифруется Fernet в БД автоматически

### Шаг 11. Импорт данных

В админке:
1. **Коллекции** → Создать (например, `ksr_main`, dim=2560 для Qwen3-Embedding-4B)
2. **Импорт** → Загрузить Excel → выбрать маппинг колонок
3. Запустить job → дождаться завершения (через **Задачи** в админке)
4. Пользоваться поиском

---

## 🚀 Способ 2: SSH вручную (если нет Portainer)

```bash
# 1. SSH на VPS
ssh root@<IP_VPS>

# 2. Установить Docker (если не установлен)
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 3. Клонировать репо
git clone https://github.com/Alexandrisius/DS-25001-VectorSearch.git
cd DS-25001-VectorSearch
git checkout refactor/v2-clean-architecture

# 4. Создать .env
cp .env.example .env
nano .env  # заполнить секреты

# 5. Поднять стек
make up          # или: docker compose up -d --build
make migrate     # или: docker compose exec api alembic upgrade head

# 6. Проверить
curl http://localhost:8000/health
make logs-api

# 7. Настроить автозапуск
# Docker Compose уже имеет restart: unless-stopped, этого достаточно
```

---

## 🔄 Обновление приложения (zero-downtime)

```bash
# 1. SSH на VPS
ssh root@<IP_VPS>
cd DS-25001-VectorSearch

# 2. Pull изменений
git pull origin refactor/v2-clean-architecture

# 3. Пересобрать и перезапустить ТОЛЬКО api (без downtime для postgres/qdrant)
make restart     # или: docker compose up -d --build --no-deps api

# 4. Если обновились миграции:
make migrate

# 5. Проверить
make logs-api
curl http://localhost:8000/health
```

В Portainer:
- Stacks → `ksr` → **Editor** → обновите compose (через Pull) → **Update the stack**

---

## 💾 Бэкапы

### Автоматические (cron)
Создайте в `/etc/cron.d/ksr-backup`:
```cron
0 3 * * * root cd /root/DS-25001-VectorSearch && /usr/local/bin/docker compose exec -T postgres pg_dump -U ksr ksr | gzip > /root/backups/ksr_$(date +\%Y\%m\%d).sql.gz
```

### Ручные
```bash
# Postgres
docker compose exec postgres pg_dump -U ksr ksr > backup_$(date +%Y%m%d).sql

# Qdrant (snapshot)
curl -X POST http://localhost:6333/snapshots
ls -la /qdrant/snapshots/  # внутри контейнера
```

Восстановление: `make restore FILE=backup_20260101.sql`

---

## ❓ Что спросить у поддержки hoster.by

1. **Шаблон VPS**: "У вас есть готовый VPS с предустановленным Docker + Portainer?"
2. **Открытие порта**: "Можно открыть TCP 8000 для моего VPS?"
3. **Backup**: "Делаете ли вы backup volumes автоматически?"
4. **SSL**: "Нужен ли мне nginx + Let's Encrypt, или достаточно Cloudflare proxy?"

---

## 🆘 Troubleshooting

### `api` контейнер не стартует
```bash
make logs-api
# Смотрим ошибки. Частая: DATABASE_URL неправильный
```

### `/health` возвращает 500
```bash
make logs-api
docker compose ps
# Проверить, что postgres и qdrant healthy
```

### `alembic upgrade head` падает
```bash
docker compose exec api alembic current
# Должен быть пустой результат. Если ошибка — проверить DATABASE_URL
```

### Порты не доступны извне
```bash
# Внутри VPS:
sudo ufw status
sudo ufw allow 8000/tcp
sudo iptables -L -n
```

### Cloudflare Tunnel "tunnel not found"
```bash
# Проверить что cloudflared в docker-compose.yml
docker compose logs cloudflared
# Проверить TUNNEL_TOKEN в env
```
