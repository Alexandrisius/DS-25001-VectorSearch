# =============================================================================
# Makefile for KSR Vector Search v2
# =============================================================================

# Documentation: docs/README.md
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
# HELP
# =============================================================================
help:
	@echo "+============================================================+"
	@echo "|  KSR Vector Search v2 - commands                          |"
	@echo "+============================================================+"
	@echo ""
	@echo "[DOCS] Documentation: docs/README.md"
	@echo ""
	@echo "--- BASIC ---------------------------------------------"
	@echo "  make up              Start the whole stack (api, postgres, qdrant, redis, worker, flower)"
	@echo "  make down            Stop the stack"
	@echo "  make restart         Restart the stack"
	@echo "  make ps              Containers status"
	@echo ""
	@echo "--- LOGS ------------------------------------------------"
	@echo "  make logs            All services"
	@echo "  make logs-api        API only"
	@echo "  make logs-celery     Celery worker only"
	@echo "  make logs-db         Postgres + Qdrant"
	@echo ""
	@echo "--- UPDATE CODE ---------------------------------------"
	@echo "  make rebuild-api     Rebuild API (after editing api/app/*.py)"
	@echo "  make rebuild         Rebuild ALL"

	@echo ""
	@echo "--- DATABASE -----------------------------------------------"
	@echo "  make migrate         Apply Alembic migrations"
	@echo "  make revision msg=...  Create new migration"
	@echo "  make shell-postgres  Enter psql"
	@echo "  make shell-qdrant    Enter Qdrant"
	@echo ""
	@echo "--- BACKUP -----------------------------------------------"
	@echo "  make backup          Backup PostgreSQL"
	@echo "  make backup-full     Backup PostgreSQL + Qdrant"
	@echo "  make restore FILE=...  Restore from dump"
	@echo ""
	@echo "--- CLOUDFLARE TUNNEL -----------------------------------"
	@echo "  make tunnel-up       Start cloudflared (needs TUNNEL_TOKEN in .env)"
	@echo "  make tunnel-down     Stop cloudflared"
	@echo "  make tunnel-logs     Cloudflared logs"
	@echo ""
	@echo "--- BROWSER ---------------------------------------------"
	@echo "  make open-site       Open site (localhost:8000)"
	@echo "  make open-admin      Open admin (localhost:8000/admin)"
	@echo "  make open-flower     Open Flower (localhost:5555)"
	@echo "  make open-docs       Open docs (docs/README.md)"
	@echo ""
	@echo "--- DEV -------------------------------------------------"
	@echo "  make shell-api       Enter API container (bash)"
	@echo "  make test            pytest"
	@echo "  make lint            ruff check"
	@echo "  make format          ruff format"
	@echo "  make clean           Remove __pycache__"
	@echo "  make prune           [WARN]  REMOVE ALL DATA"

# =============================================================================

# =============================================================================
up:
	docker compose up -d --build
	@echo ""
	@echo "[OK] Stack started:"
	@echo "   [NET] Site:    http://localhost:8000"
	@echo "   [CFG]  Admin:  http://localhost:8000/admin (admin/admin)"
	@echo "   [API] API docs: http://localhost:8000/docs"
	@echo "   [FL] Flower:   http://localhost:5555 (admin/admin)"
	@echo ""
	@echo "[TIP] Next step: make migrate"

down:
	docker compose down

restart:
	docker compose restart

ps:
	docker compose ps

# =============================================================================
# LOGS
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
# UPDATE CODE
# =============================================================================
rebuild-api:
	@echo "[BUILD] Rebuilding API..."
	docker compose build api
	@echo "[RESTART] Restarting api + celery_worker..."
	docker compose up -d api celery_worker
	@echo "[OK] Done. UI does not need restart (volume mount)."

rebuild:
	@echo "[BUILD] Rebuilding all services..."
	docker compose build
	@echo "[RESTART] Restarting..."
	docker compose up -d
	@echo "[OK] Done."

# =============================================================================
# DATABASE
# =============================================================================
migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

# =============================================================================
# BACKUP
# =============================================================================
backup:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-ksr} $${POSTGRES_DB:-ksr} \
		> data/backups/ksr_$${TS}.sql
	@echo "[OK] Backup: data/backups/ksr_$$(date +%Y%m%d_%H%M%S).sql"
	@echo "[TIP] For full backup (with Qdrant): make backup-full"

backup-full:
	@mkdir -p data/backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	docker compose exec -T postgres pg_dump -U $${POSTGRES_USER:-ksr} $${POSTGRES_DB:-ksr} \
		> data/backups/pg_$${TS}.sql; \
	docker compose exec -T qdrant tar czf - /qdrant/storage > data/backups/qdrant_$${TS}.tar.gz

	@echo "   data/backups/pg_$$(date +%Y%m%d_%H%M%S).sql"
	@echo "   data/backups/qdrant_$$(date +%Y%m%d_%H%M%S).tar.gz"

restore:
	@if [ -z "$(FILE)" ]; then echo "[X] Usage: make restore FILE=path/to/dump.sql"; exit 1; fi
	@echo "[WARN]  This will DELETE current data and replace with data from $(FILE)"
	@read -p "Continue? [y/N] " r && [ "$$r" = "y" ] || exit 1
	docker compose exec -T postgres psql -U $${POSTGRES_USER:-ksr} -d $${POSTGRES_DB:-ksr} < $(FILE)
	@echo "[OK] DB restored from $(FILE)"

# =============================================================================
# CLOUDFLARE TUNNEL
# =============================================================================
tunnel-up:
	@if [ -z "$$TUNNEL_TOKEN" ] && ! grep -q "^TUNNEL_TOKEN=." .env 2>/dev/null; then \
		echo "[X] TUNNEL_TOKEN not set in .env"; \
		echo "   1. Create tunnel: https://one.dash.cloudflare.com/ -> Zero Trust -> Networks -> Tunnels"; \
		echo "   2. Copy token to .env: TUNNEL_TOKEN=eyJh..."; \
		echo "   3. Run make tunnel-up again"; \
		exit 1; \
	fi
	@echo "[NET] Starting Cloudflare Tunnel..."
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d cloudflared
	@echo "[OK] Tunnel started. See logs: make tunnel-logs"

tunnel-down:
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml stop cloudflared
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml rm -f cloudflared
	@echo "[OK] Tunnel stopped"

tunnel-logs:
	docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml logs -f cloudflared

# =============================================================================

# =============================================================================
open-site:
	@cmd /c start http://localhost:8000 2>nul || xdg-open http://localhost:8000 2>nul || open http://localhost:8000
	@echo "[NET] Opened http://localhost:8000"

open-admin:
	@cmd /c start http://localhost:8000/admin 2>nul || xdg-open http://localhost:8000/admin 2>nul || open http://localhost:8000/admin
	@echo "[CFG]  Opened http://localhost:8000/admin (admin/admin)"

open-flower:
	@cmd /c start http://localhost:5555 2>nul || xdg-open http://localhost:5555 2>nul || open http://localhost:5555
	@echo "[FL] Opened http://localhost:5555 (admin/admin)"

open-docs:
	@cmd /c start docs/README.md 2>nul || xdg-open docs/README.md 2>nul || open docs/README.md
	@echo "[DOCS] Opened docs/README.md"

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

# =============================================================================
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "[OK] Python cache cleaned"

prune:
	@echo "[WARN]  This will DELETE all containers, volumes and data!"
	@read -p "Are you sure? [y/N] " r && [ "$$r" = "y" ] || exit 1
	docker compose down -v
	docker system prune -f
	@echo "[OK] Cleaned"
