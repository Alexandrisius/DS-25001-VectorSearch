# Безопасность: пароли, токены, секреты

Все секретные данные в проекте и как с ними работать.

## Где какие секреты

| Секрет | Где хранится | Как менять |
|---|---|---|
| **Пароль админки** | `.env` (как bcrypt хеш) | `make password NEW=xxx` |
| **API ключ OpenRouter** | БД (зашифрован Fernet) | Через админку (UI) |
| **JWT secret** | `.env` (открытым текстом) | `make rebuild-api` после правки .env |
| **Fernet key** | `.env` (открытым текстом) | `make rebuild-api` после правки .env |
| **Postgres password** | `.env` (открытым текстом) | `make rebuild-api` после правки .env |
| **Cloudflare Tunnel token** | `.env` (открытым текстом) | `make tunnel-up` (читает из .env) |
| **Flowеr basic auth** | `.env` (открытым текстом) | `make rebuild` после правки .env |

## Сменить пароль админки

### Способ 1: одной командой (рекомендуется)

```bash
make password NEW=MyNewPassword123
```

Скрипт сам:
1. Сгенерирует bcrypt хеш
2. Обновит `.env` (с экранированием `$$` для Docker)
3. Пересоберёт API
4. Перезапустит контейнеры

Готово. Можно заходить с новым паролем.

### Способ 2: PowerShell

```powershell
.\make.ps1 password MyNewPassword123
```

### Способ 3: вручную (если make не работает)

```bash
# 1. Сгенерировать хеш
python scripts/change_password.py MyNewPassword123
# Только обновит .env

# 2. Перезапустить
make rebuild-api
```

### Способ 4: совсем вручную

```bash
# 1. Сгенерировать bcrypt хеш
python -c "import bcrypt; print(bcrypt.hashpw(b'MyNewPassword', bcrypt.gensalt(rounds=12).decode())"

# Скопировать вывод (вида: $2b$12$abc...xyz)

# 2. Открыть .env
# 3. Заменить строку ADMIN_PASSWORD_HASH=...
# ВАЖНО: каждый $ удвоить → $$ (для Docker)
# Было:  $2b$12$abc...xyz
# Стало: $$2b$$12$$abc...xyz

# 4. Перезапустить
make rebuild-api
```

## Что НЕЛЬЗЯ делать с паролем

- **Коммитить в git** — `.env` в `.gitignore`, проверьте
- **Слать в чат/почту** — это секрет
- **Использовать в проде дефолтный "admin"** — смените перед деплоем

## Сменить API ключ OpenRouter

Только через админку (не через .env):

1. Открой http://localhost:8000/admin
2. Настройки → LLM API
3. Впиши новый ключ
4. Нажми **Сохранить**

Ключ шифруется Fernet и хранится в БД (`api_providers.api_key_encrypted`).

## Сменить JWT secret (если скомпрометирован)

```bash
# 1. Сгенерировать новый
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 2. Вписать в .env: JWT_SECRET_KEY=...
# 3. Перезапустить
make rebuild-api
```

⚠️ **Все активные JWT-токены перестанут работать** — пользователям нужно заново войти.

## Сменить Fernet key

```bash
# 1. Сгенерировать
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Вписать в .env: ENCRYPTION_KEY=...
# 3. Перезапустить
make rebuild-api
```

⚠️ **Все зашифрованные данные в БД (API ключи OpenRouter) станут нечитаемыми!** Нужно будет заново ввести их через админку.

## Сменить пароль PostgreSQL

```bash
# 1. Сгенерировать
openssl rand -base64 16

# 2. Обновить .env
POSTGRES_PASSWORD=новый_пароль
DATABASE_URL=postgresql+asyncpg://ksr:новый_пароль@postgres:5432/ksr
SYNC_DATABASE_URL=postgresql://ksr:новый_пароль@postgres:5432/ksr

# 3. Сменить в самой БД (подключиться к контейнеру)
make shell-postgres
# Внутри psql:
ALTER USER ksr PASSWORD 'новый_пароль';
\q

# 4. Перезапустить
make rebuild
```

## Сменить Cloudflare Tunnel

1. https://one.dash.cloudflare.com/ → Zero Trust → Networks → Tunnels
2. Старый туннель → Delete
3. Create a tunnel → имя `ksrmatch` → Save
4. Скопировать новый токен
5. Вписать в `.env`: `TUNNEL_TOKEN=eyJh...`
6. `make tunnel-down && make tunnel-up`

## Если что-то сломалось после смены секретов

1. Проверь логи: `make logs-api`
2. Проверь что `.env` не содержит синтаксических ошибок
3. Самый надёжный способ — откатить `.env` из бэкапа: `make backup` перед сменой
