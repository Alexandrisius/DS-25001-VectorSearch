# =============================================================================
# Makefile для KSR Vector Search v2
# =============================================================================
# Подсказка: запускай `make` или `make help` чтобы увидеть все команды.
# Документация: docs/README.md
# =============================================================================

.PHONY: help up down restart ps \
        logs logs-api logs-worker logs-celery logs-db \
        shell-api shell-worker shell-postgres shell-qdrant \
        migrate revision rebuild-api rebuild \
        backup backup-full restore \
        tunnel-up tunnel-down tunnel-logs \
        open-admin open-site open-flower open-docs \
        test lint format clean prune

# =============================================================================
# ПОМОЩЬ
# =============================================================================
help:
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║  KSR Vector Search v2 — команды                            ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📖 Документация: docs/README.md"
	@echo ""
	@echo "━━━ БАЗОВЫЕ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make up              Поднять весь стек (api, postgres, qdrant, redis, worker, flower)"
	@echo "  make down            Остановить стек"
	@echo "  make restart         Перезапустить стек"
	@echo "  make ps              Статус контейнеров"
	@echo ""
	@echo "━━━ ЛОГИ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make logs            Все сервисы"
	@echo "  make logs-api        Только API"
	@echo "  make logs-celery     Только Celery worker"
	@echo "  make logs-db         Postgres + Qdrant"
	@echo ""
	@echo "━━━ ОБНОВЛЕНИЕ КОДА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make rebuild-api     Пересобрать API (после правок api/app/*.py)"
	@echo "  make rebuild         Пересобрать ВСЁ"
	@echo "  ⚠️  Для UI (web/*) рестарт НЕ нужен — обнови вкладку браузера"
	@echo ""
	@echo "━━━ БД ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make migrate         Применить миграции Alembic"
	@echo "  make revision msg=…  Создать новую миграцию"
	@echo "  make shell-postgres  Войти в psql"
	@echo "  make shell-qdrant    Войти в Qdrant"
	@echo ""
	@echo "━━━ БЭКАП ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make backup          Бэкап PostgreSQL"
	@echo "  make backup-full     Бэкап PostgreSQL + Qdrant"
	@echo "  make restore FILE=…  Восстановить из дампа"
	@echo ""
	@echo "━━━ CLOUDFLARE TUNNEL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make tunnel-up       Запустить cloudflared (нужен TUNNEL_TOKEN в .env)"
	@echo "  make tunnel-down     Остановить cloudflared"
	@echo "  make tunnel-logs     Логи cloudflared"
	@echo ""
	@echo "━━━ BROWSER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make open-site       Открыть сайт (localhost:8000)"
	@echo "  make open-admin      Открыть админку (localhost:8000/admin)"
	@echo "  make open-flower     Открыть Flower (localhost:5555)"
	@echo "  make open-docs       Открыть документацию (docs/README.md)"
	@echo ""
	@echo "━━━ DEV ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  make shell-api       Войти в контейнер API (bash)"
	@echo "  make test            pytest"
	@echo "  make lint            ruff check"
	@echo "  make format          ruff format"
	@echo "  make clean           Удалить __pycache__"
	@echo "  make prune           ⚠️  Удалить ВСЕ ДАННЫЕ"

# =============================================================================
# СТЕК
# =============================================================================
up:
	docker compose up -d --build
	@echo ""
	@echo "✅ Стек поднят:"
	@echo "   🌐 Сайт:    http://localhost:8000"
	@echo "   ⚙️  Админка:  http://localhost:8000/admin (admin/admin)"
	@echo "   📚 API docs: http://localhost:8000/docs"
	@echo "   🌸 Flower:   http://localhost:5555 (admin/admin)"
	@echo ""
	@echo "💡 Следующий шаг: make migrate"

down:
	docker compose down

restart:
	docker compose restart

ps:
	docker compose ps

# =============================================================================
# ЛОГИ
# =============================================================================
logs:
	docker compose logs -f --tail=100

logs-api:
	docker compose logs -f api

logs-celery:
	docker compose logs -f celery_worker

logs-worker: logs-celery

logs-db:
	docker compose logs -f postgres qdrant

# =============================================================================
# SHELL
# =============================================================================
shell-api:
	docker compose exec api bash

shell-worker:
	docker compose exec celery_worker bash

shell-postgres:
	docker compose exec postgres psql -U $${POSTGRES_USER:-ksr} -d $${POSTGRES_DB:-ksr}

shell-qdrant:
	docker compose exec qdrant sh

# =============================================================================
# ОБНОВЛЕНИЕ КОДА
# =============================================================================
rebuild-api:
	@echo "🔨 Пересобираю API..."
	docker compose build api
	@echo "🔄 Перезапускаю api + celery_worker..."
	docker compose up -d api celery_worker
	@echo "✅ Готово. UI не требует рестарта (volume mount)."

rebuild:
	@echo "🔨 Пересобираю все сервисы..."
	docker compose build
	@echo "🔄 Перезапускаю..."
	docker compose up -d
	@echo "✅ Готово."

# =============================================================================
# БД
# =============================================================================
migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

# =============================================================================
# БЭКАП
# =============================================================================
backup:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-ksr} $${POSTGRES_DB:-ksr} \
		> data/backups/ksr_$${TS}.sql
	@echo "✅ Бэкап: data/backups/ksr_$$(date +%Y%m%d_%H%M%S).sql"
	@echo "💡 Для полного бэкапа (с Qdrant): make backup-full"

backup-full:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-ksr} $${POSTGRES_DB:-ksr} \
		> data/backups/pg_$${TS}.sql; \
	docker compose exec -T qdrant tar czf - /qdrant/storage > data/backups/qdrant_$${TS}.tar.gz
	@echo "✅ Полный бэкап:"
	@echo "   data/backups/pg_$$(date +%Y%m%d_%H%M%S).sql"
	@echo "   data/backups/qdrant_$$(date +%Y%m%d_%H%M%S).tar.gz"

restore:
	@if [ -z "$(FILE)" ]; then echo "❌ Использование: make restore FILE=path/to/dump.sql"; exit 1; fi
	@echo "⚠️  Это УДАЛИТ текущие данные и заменит их на данные из $(FILE)"
	@read -p "Продолжить? [y/N] " r && [ "$$r" = "y" ] || exit 1
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-ksr} -d $${POSTGRES_DB:-ksr} < $(FILE)
	@echo "✅ БД восстановлена из $(FILE)"

# =============================================================================
# CLOUDFLARE TUNNEL
# =============================================================================
tunnel-up:
	@if [ -z "$$TUNNEL_TOKEN" ] && ! grep -q "^TUNNEL_TOKEN=." .env 2>/dev/null; then \
		echo "❌ TUNNEL_TOKEN не задан в .env"; \
		echo "   1. Создай туннель: https://one.dash.cloudflare.com/ → Zero Trust → Networks → Tunnels"; \
		echo "   2. Скопируй токен в .env: TUNNEL_TOKEN=eyJh..."; \
		echo "   3. Повтори make tunnel-up"; \
		exit 1; \
	fi
	@echo "🌐 Запускаю Cloudflare Tunnel..."
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d cloudflared
	@echo "✅ Tunnel запущен. Смотри логи: make tunnel-logs"

tunnel-down:
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml stop cloudflared
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml rm -f cloudflared
	@echo "✅ Tunnel остановлен"

tunnel-logs:
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml logs -f cloudflared

# =============================================================================
# BROWSER (открыть в дефолтном браузере)
# =============================================================================
open-site:
	@cmd /c start http://localhost:8000 2>nul || xdg-open http://localhost:8000 2>nul || open http://localhost:8000
	@echo "🌐 Открыл http://localhost:8000"

open-admin:
	@cmd /c start http://localhost:8000/admin 2>nul || xdg-open http://localhost:8000/admin 2>nul || open http://localhost:8000/admin
	@echo "⚙️  Открыл http://localhost:8000/admin (admin/admin)"

open-flower:
	@cmd /c start http://localhost:5555 2>nul || xdg-open http://localhost:5555 2>nul || open http://localhost:5555
	@echo "🌸 Открыл http://localhost:5555 (admin/admin)"

open-docs:
	@cmd /c start docs/README.md 2>nul || xdg-open docs/README.md 2>nul || open docs/README.md
	@echo "📖 Открыл docs/README.md"

# =============================================================================
# DEV / TEST
# =============================================================================
test:
	docker compose exec api pytest -v

lint:
	docker compose exec api ruff check app

format:
	docker compose exec api ruff format app

# =============================================================================
# ОЧИСТКА
# =============================================================================
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Кэш Python очищен"

prune:
	@echo "⚠️  Это УДАЛИТ все контейнеры, volumes и данные!"
	@read -p "Точно? [y/N] " r && [ "$$r" = "y" ] || exit 1
	docker compose down -v
	docker system prune -f
	@echo "✅ Очищено"
