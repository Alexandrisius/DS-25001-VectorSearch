# 08. Развернуть на VPS (когда надоест дома)

VPS — это арендованный сервер в интернете. Сайт будет работать 24/7, не зависит от твоего ПК и твоего интернета.

## Когда это нужно

- Сайт нужен **круглосуточно** (а не только когда у тебя включён ПК)
- Хочешь **нормальный домен** без `host.docker.internal`
- Надоело держать ПК включённым

## Рекомендуемые провайдеры (РФ)

| Провайдер | Мин. цена | Где смотреть |
|---|---|---|
| **hoster.by** | ~15 BYN/мес | https://hoster.by/ |
| **reg.ru** | ~300 ₽/мес | https://reg.ru/vps/ |
| **timeweb.cloud** | ~200 ₽/мес | https://timeweb.cloud/ |

Минимальные требования: **2 ГБ RAM, 2 vCPU, 20 ГБ SSD**.

## Шаг 1. Купи VPS

ОС: **Ubuntu 22.04 LTS** или **Debian 12**

При покупке:
- Выбери регион (ближе к тебе = быстрее)
- Скачай **SSH-ключ** (или создай свой — `ssh-keygen -t ed25519`)
- Запини IP-адрес сервера (например `135.181.xx.xx`)

## Шаг 2. Подключись к серверу

```bash
ssh root@135.181.xx.xx
```

## Шаг 3. Установи Docker

```bash
# Обновить систему
apt update && apt upgrade -y

# Установить Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Проверить
docker --version
```

## Шаг 4. Скопируй проект на сервер

**Вариант A:** через git (если код в репозитории)
```bash
git clone https://github.com/your-user/DS-25001-VectorSearch.git
cd DS-25001-VectorSearch
```

**Вариант B:** через scp
```bash
# На своём ПК:
scp -r "C:\Users\klim9\Yandex.Disk\02_Work\#Projects\04_DataScience\DS-25001-VectorSearch" root@135.181.xx.xx:/root/
```

## Шаг 5. Сгенерируй секреты

На **своём ПК** (не на сервере!) сгенерируй новые секреты:

```bash
# Bcrypt хеш пароля (замени 'MySecretPassword123' на свой пароль)
python -c "import bcrypt; print(bcrypt.hashpw(b'MySecretPassword123', bcrypt.gensalt()).decode())"

# JWT secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Fernet key для шифрования API ключей
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Шаг 6. Создай `.env` на сервере

```bash
cd /root/DS-25001-VectorSearch
cp .env.example .env
nano .env   # или vim
```

Заполни **обязательно**:
- `POSTGRES_PASSWORD` — сложный пароль (не `change-me`)
- `ADMIN_PASSWORD_HASH` — bcrypt хеш из шага 5
- `JWT_SECRET_KEY` — из шага 5
- `ENCRYPTION_KEY` — из шага 5
- `OPENROUTER_API_KEY` — свой ключ

Сохрани (`Ctrl+O`, `Enter`, `Ctrl+X` в nano).

## Шаг 7. Подними стек

```bash
make up
make migrate
```

Подожди 30 секунд.

## Шаг 8. Настрой Cloudflare Tunnel (опционально)

Если хочешь красивый домен — см. [06-tunnel.md](06-tunnel.md).

Или простой вариант: **nginx + Let's Encrypt** для HTTPS.

### nginx + Let's Encrypt

```bash
# Установить
apt install -y nginx certbot python3-certbot-nginx

# Создать конфиг
cat > /etc/nginx/sites-available/ksr <<'EOF'
server {
    server_name ksrmatch.online www.ksrmatch.online;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -s /etc/nginx/sites-available/ksr /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Получить HTTPS сертификат
certbot --nginx -d ksrmatch.online -d www.ksrmatch.online
```

Теперь сайт доступен по `https://ksrmatch.online`.

## Шаг 9. Настрой файрвол

```bash
ufw allow 22        # SSH
ufw allow 80        # HTTP
ufw allow 443       # HTTPS
ufw enable
```

## Шаг 10. Автообновление (опционально)

Создай cron-задачу для бэкапа:

```bash
crontab -e
# Добавь:
0 3 * * * cd /root/DS-25001-VectorSearch && make backup
```

## Управление сервером

```bash
# Зайти на сервер
ssh root@135.181.xx.xx

# Посмотреть логи
cd /root/DS-25001-VectorSearch
make logs

# Обновить код
git pull
make rebuild-api
make migrate

# Перезапустить
make restart
```

## Безопасность (ОБЯЗАТЕЛЬНО)

1. **Смени пароль root** или отключи вход по паролю
2. **Создай отдельного пользователя** для деплоя (не работай под root)
3. **Не открывай порт 8000 наружу** — он уже спрятан за nginx
4. **Настрой fail2ban** для защиты SSH
5. **Регулярно обновляй** систему: `apt update && apt upgrade`

## Мониторинг (опционально)

- **Uptime Kuma** — простой мониторинг доступности (http://localhost:3001)
- **Grafana + Prometheus** — для продвинутых

## Если что-то сломалось

```bash
# Полная перезагрузка стека
cd /root/DS-25001-VectorSearch
make down
make up
make migrate

# Логи
make logs-api | tail -100
```

## Стоимость

| Статья | ~Цена в месяц |
|---|---|
| VPS 2 ГБ | 300-500 ₽ |
| Домен | 100-500 ₽/год |
| OpenRouter | $5-20 (зависит от объёма) |
| Cloudflare Tunnel | бесплатно |
| **Итого** | **~500-700 ₽/мес** |
