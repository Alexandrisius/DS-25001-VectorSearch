# AGENTS.md

> **Read this first if you are an AI agent working on this project.**
> This file is a system prompt, not documentation. Keep it <250 lines.
> Detailed docs live in `docs/`. Link, don't paste.

## 1. What is this

KSR Vector Search v2 — semantic search for Russian construction classifier
(КСР/Классификатор строительных ресурсов). Two-stage retrieval
(Qdrant vectors → BM25 → Cohere rerank via OpenRouter).

- **Stack:** Python 3.12 + FastAPI + SQLAlchemy 2.0 async + Pydantic v2 +
  PostgreSQL 16 + Qdrant 1.18 (gRPC) + Redis + Celery + Docker
- **Branch:** `refactor/v2-clean-architecture`
- **User:** non-developer in Minsk (UTC+3), 1 project, hates long docs.
- **Conversation:** Russian. Format: numbered steps, 1 command = 1 line.
- **Admin password:** `PassatAdmin!#`
- **No tests** (pytest). Manual smoke tests in `C:\tmp\test_*.py`.

Full project description → `docs/00-overview.md`

## 2. Commands (the single highest-ROI section)

```bash
make help                # full command list
make up && make migrate  # first start
make open-admin          # open http://localhost:8000/admin
make logs-api            # tail API logs
make rebuild-api         # REQUIRED after Python changes (api + worker)
make migrate             # apply Alembic migrations
make revision msg=foo    # create new migration (then rebuild-api!)
make backup              # Postgres dump to data/backups/
make shell-postgres      # psql
make shell-qdrant        # qdrant container shell
make tunnel-up           # start Cloudflare tunnel
```

**Two-step rule for new migrations** (committing this mistake = broken state):
1. `make rebuild-api` — copies new migration file into container image
2. `make migrate` — alembic upgrade head

Skip step 1 → "no new migrations found". Gotcha 10.16 in `docs/05-gotchas.md`.

## 3. Architecture

```
Routers (api/*.py)        <- thin: parse, call service, return
  -> Services (services/) <- business logic
    -> Models (models/)   <- SQLAlchemy 2.0 async ORM
```

Frontend: **plain HTML/CSS/JS, no build step, no npm**. Volume-mounted
into api container (`./web:/app/web:ro`) → changes visible without rebuild.
Bump `?v=X.Y.Z` in `admin.html` to bust browser cache.

Background jobs: Celery. Each task is `app.workers.tasks.<name>_task`.
WebSocket progress: `/admin/jobs/{id}/ws` (Redis pub/sub `job:{id}`).

## 4. Workflow after editing

| Edit | Command |
|---|---|
| `api/app/**/*.py` | `make rebuild-api` |
| New `api/alembic/versions/*.py` | `make rebuild-api` THEN `make migrate` |
| `web/static/**` | Refresh browser (`Ctrl+Shift+R`) |
| `web/admin.html` (JS version) | Bump `?v=` in `<script src=...>` |
| `Makefile` / `docker-compose.yml` | `make restart` (no rebuild needed) |
| `web/static/css/**` | Bump `?v=` in `<link href=...>` |

## 5. Critical Gotchas (READ FIRST — top 7)

Full list (10.1-10.18) in `docs/05-gotchas.md`. These seven are
non-obvious and will burn you without warning:

### 5.1 OpenRouter needs ALL 4 headers (User-Agent too)
```python
headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "User-Agent": "KSR-Matcher/2.0",   # NOT python-httpx default
    "HTTP-Referer": "https://ksrmatch.online/",
    "X-Title": "KSR Matcher",            # OLD name, NOT X-OpenRouter-Title
}
```
Cloudflare guardrail blocks the default `python-httpx/x.x.x`. Custom UA passes.

### 5.2 Worker cancellation: tasks.py MUST NOT re-set status
`JobService.cancel()` sets `status=CANCELLED` in БД. If `tasks.py` does
`UPDATE status=COMPLETED` after `import_records`, it overwrites CANCELLED.
→ Remove the duplicate UPDATE in `tasks.py` (line 141-150). ImportService
itself sets COMPLETED with details.

### 5.3 Folder rebuild: bulk embed_batch, NOT sequential embed_one
```python
# WRONG: 1500 sequential HTTP calls = 30+ min
for f in new_folders:
    vector = await self.embedding.embed_one(f["full_path"])
    qdrant.upsert(coll, [PointStruct(id=..., vector=vector)])

# RIGHT: one bulk call, one batch upsert
vectors = await self.embedding.embed_batch([f["full_path"] for f in new_folders])
points = [PointStruct(id=..., vector=v, payload=p) for f, v in zip(...)]
qdrant.upsert(coll, points=points)  # ONE call
```

### 5.4 /admin/collections: stored counter, NOT COUNT(*)
For 142k records `SELECT COUNT(*) ...` = 2-3 sec lag. Use
`collections.materials_count` (added in Alembic 0003, backfilled).
`ImportService._upsert_materials_bulk` increments on each chunk.

### 5.5 Qdrant: gRPC, not HTTP (32 MB hard limit)
HTTP API hardcoded 32 MB payload limit. 142k codes via MatchAny = 90 MB.
Use `QdrantClient(prefer_grpc=True, grpc_port=6334, grpc_options={...})`.
Requires `QDRANT__SERVICE__GRPC_PORT: 6334` + `6334:6334` port map.

### 5.6 Alembic new migration: rebuild-api BEFORE migrate
Container has no volume mount for Python — `./api` is BAKED INTO IMAGE
at build time. New migration file is invisible until rebuild.

### 5.7 bcrypt in .env: escape `$$`
```bash
# WRONG: $1 in bash expands to empty
ADMIN_PASSWORD_HASH=$2b$12$...
# RIGHT: $$ survives bash + docker-compose interpolation
ADMIN_PASSWORD_HASH=$$2b$$12$$...
```

## 6. Boundaries (three-tier)

**Always:**
- Use `make` (not `docker compose` directly)
- `make rebuild-api` after Python changes
- Bump `?v=` in HTML after JS/CSS changes
- Match existing code style (no new patterns, no new deps without asking)
- Commit with format `<type>(scope): description` (English)

**Ask first:**
- New dependencies in `pyproject.toml`
- New top-level directories
- Deleting files
- Schema changes to existing tables

**Never:**
- Commit secrets (`.env`, API keys, bcrypt hashes)
- Push `feature-qdrant` branch (leaked OpenRouter key in history)
- Use HTTP API for Qdrant bulk operations
- Re-set `status=COMPLETED` in `tasks.py` after `import_records`
- Use `npm`, `webpack`, build steps in `web/`
- Add `print()` — use `loguru.logger`
- Use `git push --force` without explicit permission

## 7. When something doesn't work

1. `make logs-api` — look for traceback
2. Is migration applied? `make migrate`
3. Did you forget `make rebuild-api`?
4. Browser: hard refresh (`Ctrl+Shift+R`)
5. Stuck? Read `docs/05-gotchas.md` (10.1-10.18)
6. Still stuck? Read relevant `docs/NN-*.md`

## 8. Things NOT to ask the user

- Admin password (`PassatAdmin!#`)
- How to start (`make up && make migrate`)
- Port numbers (see Makefile / `docs/01-architecture.md`)
- OpenRouter key location (DB, Fernet-encrypted)
- OpenRouter header format (gotcha 5.1)
- Branch (`refactor/v2-clean-architecture`)

## 9. Things OK to ask

- Cloudflare `TUNNEL_TOKEN` (in `.env`, not in repo)
- Domain choice (currently `ksrmatch.online`)
- New admin password (if changing)
- Business logic decisions (column mapping rules, etc.)

## 10. Related docs

| File | When to read |
|---|---|
| `docs/00-overview.md` | Project context, user goals, business rules |
| `docs/01-architecture.md` | Clean architecture layers, request flow |
| `docs/02-daily-work.md` | Day-to-day commands and workflow |
| `docs/03-update-code.md` | Pulling code, rebuilding, rollback |
| `docs/04-commands.md` | Full Makefile reference (30+ commands) |
| `docs/05-gotchas.md` | All 10.x gotchas with code samples |
| `docs/06-tunnel.md` | Cloudflare Tunnel setup |
| `docs/07-data.md` | Data import, Excel format, column mapping |
| `docs/08-deploy-vps.md` | Production deployment to VPS |
| `docs/09-security-secrets.md` | Fernet, JWT, bcrypt, .env structure |

**Last updated:** 2026-06-11 (refactor/v2-clean-architecture) — rewrote as
lean system prompt (was 700+ lines, now 230), moved detail to `docs/`.
