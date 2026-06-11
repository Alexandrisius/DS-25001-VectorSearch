# =============================================================================
# Makefile для KSR Vector Search v2
# =============================================================================
# Использование: make <command>
# =============================================================================

.PHONY: help up down restart logs logs-api logs-worker ps shell-api shell-worker \
        migrate revision superuser test lint format clean prune backup restore \
        stop-all seed run-local

# ---------- Помощь ----------
help:
	@echo "KSR Vector Search v2 - команды:"
	@echo ""
	@echo "  make up              — поднять весь стек (api + postgres + qdrant + redis + worker + flower)"
	@echo "  make down            — остановить стек"
	@echo "  make restart         — перезапустить стек"
	@echo "  make ps              — статус контейнеров"
	@echo ""
	@echo "  make logs            — логи всех сервисов"
	@echo "  make logs-api        — логи api"
	@echo "  make logs-worker     — логи celery worker"
	@echo ""
	@echo "  make shell-api       — зайти в контейнер api (bash)"
	@echo "  make shell-worker    — зайти в контейнер celery"
	@echo "  make shell-postgres  — зайти в postgres CLI"
	@echo ""
	@echo "  make migrate         — применить миграции Alembic"
	@echo "  make revision msg=…  — создать новую миграцию"
	@echo ""
	@echo "  make test            — запустить pytest"
	@echo "  make lint            — ruff check"
	@echo "  make format          — ruff format"
	@echo ""
	@echo "  make backup          — снапшот БД (data/backups/)"
	@echo "  make restore FILE=…  — восстановить из дампа"
	@echo ""
	@echo "  make clean           — удалить __pycache__"
	@echo "  make prune           — остановить и удалить volumes (УДАЛИТ ДАННЫЕ!)"

# ---------- Стек ----------
up:
	docker compose up -d --build
	@echo ""
	@echo "✅ Стек поднят:"
	@echo "   API:    http://localhost:8000"
	@echo "   Admin:  http://localhost:8000/admin"
	@echo "   Docs:   http://localhost:8000/docs"
	@echo "   Flower: http://localhost:5555 (admin:admin)"

down:
	docker compose down

restart:
	docker compose restart

stop-all:
	docker compose stop

ps:
	docker compose ps

# ---------- Логи ----------
logs:
	docker compose logs -f --tail=100

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f celery_worker

logs-db:
	docker compose logs -f postgres qdrant

# ---------- Shell ----------
shell-api:
	docker compose exec api bash

shell-worker:
	docker compose exec celery_worker bash

shell-postgres:
	docker compose exec postgres psql -U $${POSTGRES_USER:-ksr} -d $${POSTGRES_DB:-ksr}

# ---------- Миграции ----------
migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

# ---------- Тесты и линт ----------
test:
	docker compose exec api pytest -v

lint:
	docker compose exec api ruff check app

format:
	docker compose exec api ruff format app

# ---------- Бэкап / Восстановление ----------
backup:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-ksr} $${POSTGRES_DB:-ksr} \
		> data/backups/ksr_$${TS}.sql
	@echo "✅ Бэкап сохранён в data/backups/ksr_$$(date +%Y%m%d_%H%M%S).sql"
	@echo "   Для Qdrant снапшот: docker compose exec qdrant curl -X POST http://localhost:6333/snapshots"

restore:
	@if [ -z "$(FILE)" ]; then echo "❌ Использование: make restore FILE=path/to/dump.sql"; exit 1; fi
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-ksr} -d $${POSTGRES_DB:-ksr} < $(FILE)
	@echo "✅ БД восстановлена из $(FILE)"

# ---------- Утилиты ----------
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Кэш Python очищен"

prune:
	@echo "⚠️  Удаляю контейнеры и volumes (ВСЕ ДАННЫЕ БУДУТ ПОТЕРЯНЫ!)"
	@read -p "Точно? [y/N] " r && [ "$$r" = "y" ] || exit 1
	docker compose down -v
	docker system prune -f
	@echo "✅ Очищено"
