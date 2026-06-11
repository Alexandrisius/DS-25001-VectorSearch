# AGENTS.md

> **Read this first if you are an AI agent working on this project.**
> This document is self-contained. It tells you everything you need to know
> to be productive without asking the user basic questions about the project.

---

## 1. What is this project?

**KSR Vector Search v2** - semantic search engine for Russian construction
classifier (KSR / KSR (construction resources classifier)) with two-stage
retrieval (vector + rerank) and OpenRouter API integration.

- **Purpose:** search through materials catalog (codes + descriptions)
- **Stack:** Python 3.12 + FastAPI + PostgreSQL 16 + Qdrant + Redis + Celery + Docker
- **Current branch:** `refactor/v2-clean-architecture`
- **User:** one developer + their friends (uses locally, not in production)
- **Conversation language:** Russian (user writes in Russian, prefer Russian in responses)

### The user in one sentence
A non-developer who:
- Hates typing long commands
- Forgets how the server was set up between sessions
- Wants a single command to do anything
- Will not read long docs but will look at numbered steps
- Already changed admin password to `PassatAdmin!#` (so you know - they have a VW Passat)

---

## 2. TL;DR - Quick Start (30 seconds)

```bash
# Start everything
make up

# Apply DB migrations
make migrate

# Open admin panel
make open-admin
# Login: admin / PassatAdmin!#

# See logs
make logs-api
```

**That's it.** User uses `make` (installed in `C:\Users\klim9\bin\`).
All commands are defined in `Makefile`. PowerShell fallback: `make.ps1`.

For full command list: `make help`

---

## 3. Project Structure

```
DS-25001-VectorSearch/
|-- api/                          # Python backend
|   |-- app/
|   |   |-- api/                  # FastAPI routers (admin, search, etc.)
|   |   |   |-- admin.py          # /admin/* (collections CRUD)
|   |   |   |-- admin_data.py     # /admin/databases (data view)
|   |   |   |-- collections.py    # /databases
|   |   |   |-- feedback.py       # /feedback/*
|   |   |   |-- hierarchy.py      # /hierarchy/*
|   |   |   |-- import_export.py  # /import
|   |   |   |-- materials.py
|   |   |   |-- search.py         # /match (the main search endpoint)
|   |   |   |-- settings.py       # /admin/openrouter-* (LLM API config)
|   |   |   `-- system.py         # /health, /
|   |   |-- core/                 # config, security, exceptions, logging
|   |   |-- db/                   # postgres, qdrant, redis clients
|   |   |-- models/               # SQLAlchemy ORM models
|   |   |-- repositories/         # Data access layer
|   |   |-- schemas/              # Pydantic v2 schemas (request/response)
|   |   |-- services/             # Business logic
|   |   |   |-- embedding_service.py   # OpenRouter embeddings
|   |   |   |-- rerank_service.py      # OpenRouter /rerank
|   |   |   |-- search_service.py      # 2-stage retrieval
|   |   |   |-- collection_service.py  # Qdrant collections
|   |   |   |-- import_service.py      # Excel import
|   |   |   |-- feedback_service.py    # feedback_events table
|   |   |   |-- folder_service.py
|   |   |   |-- hierarchy_service.py
|   |   |   |-- material_service.py
|   |   |   |-- cleaning_runner.py
|   |   |   `-- settings_service.py    # api_providers, statuses, rules
|   |   |-- workers/              # Celery tasks
|   |   |-- utils/
|   |   |-- config.py             # Pydantic settings (via @property, see Gotchas)
|   |   |-- deps.py               # FastAPI dependencies
|   |   `-- main.py               # FastAPI app entry point
|   |-- alembic/                  # DB migrations
|   |   `-- versions/
|   |       |-- 2026_06_11_0001_0001_init_schema.py
|   |       `-- 2026_06_11_0002_0002_add_base_url.py
|   |-- pyproject.toml
|   `-- Dockerfile
|
|-- web/                          # Frontend (as-is, no build step)
|   |-- index.html                # Main search page
|   |-- admin.html                # Admin panel
|   `-- static/
|       |-- css/                  # styles.css, admin.css, font-awesome.min.css
|       |-- js/
|       |   |-- app.js            # 2021 lines - main page logic
|       |   `-- admin.js          # 4690 lines - admin logic (GOD FILE!)
|       |-- img/
|       `-- favicon.svg
|
|-- deploy/                       # Deployment scripts
|   |-- hoster-by.md              # Deploy to hoster.by VPS
|   |-- backup.sh / restore.sh
|   `-- prod.env.example
|
|-- docs/                         # User-facing documentation (Russian)
|   |-- README.md                 # Index
|   |-- 01-first-run.md
|   |-- 02-daily-work.md
|   |-- 03-update-code.md
|   |-- 04-api-key.md
|   |-- 05-lm-studio.md
|   |-- 06-tunnel.md
|   |-- 07-data.md
|   |-- 08-deploy-vps.md
|   `-- 09-security-secrets.md
|
|-- scripts/                      # Helper scripts
|   `-- change_password.py        # Generate bcrypt hash for admin
|
|-- docker-compose.yml            # 6 main services
|-- docker-compose.cloudflared.yml # Optional: Cloudflare tunnel override
|-- Makefile                      # Pure ASCII, no Unicode
|-- make.ps1                      # PowerShell fallback
|-- AGENTS.md                     # This file (for AI agents)
|-- .env                          # Real secrets (gitignored)
|-- .env.example                  # Template
`-- README.md
```

---

## 4. The Stack (in detail)

| Component | Image | Port | Purpose |
|---|---|---|---|
| **api** | custom (uv + python 3.12) | 8000 | FastAPI backend |
| **celery_worker** | same as api | - | Background jobs (import, folder rebuild) |
| **flower** | mher/flower:2.0 | 5555 | Celery monitoring (admin/admin) |
| **postgres** | postgres:16-alpine | 5432 | Main database |
| **qdrant** | qdrant/qdrant:latest | 6333 | Vector search engine |
| **redis** | redis:7-alpine | 6379 | Cache + Celery broker |
| **cloudflared** | cloudflare/cloudflared | - | Optional, via override file |

**Important:** No local ML models. All embeddings/reranking go through
OpenRouter API (or custom OpenAI-compatible endpoint like LM Studio).

---

## 5. Key Files (read these first)

| File | Why it's important |
|---|---|
| `Makefile` | All commands. Run `make help` to see everything. |
| `make.ps1` | PowerShell equivalent of Makefile (use if no `make`). |
| `.env` | Real secrets (gitignored). Contains ADMIN_PASSWORD_HASH, JWT_SECRET_KEY, ENCRYPTION_KEY, OPENROUTER_API_KEY. |
| `docker-compose.yml` | 6 services. cloudflared is in a separate override file. |
| `api/app/config.py` | Settings via Pydantic `@property` (NOT direct fields) - see Gotchas. |
| `api/app/main.py` | FastAPI app. Static files mounted from `/app/web`. |
| `api/app/services/embedding_service.py` | OpenRouter /embeddings. Uses `_resolve_embed_url()` for OpenAI-compatible endpoints. |
| `api/app/services/rerank_service.py` | OpenRouter /rerank. **Use X-Title (old), NOT X-OpenRouter-Title.** |
| `api/app/api/settings.py` | `/admin/openrouter-settings` GET/PUT + `/admin/openrouter-test` POST. |
| `web/admin.html` | Admin UI. Two status blocks (embed + rerank). |
| `web/static/js/admin.js` | **4690 lines, GOD FILE. Main refactoring target (see Section 13).** |

---

## 6. Daily Workflow

### Start work
```bash
make up            # Start all containers
make migrate       # Apply DB migrations (idempotent)
make open-admin    # Open http://localhost:8000/admin in browser
```

### After editing Python (`api/app/...`)
```bash
make rebuild-api   # Rebuild + restart api + celery_worker (~30s)
```

### After editing UI (`web/...`)
**NO RESTART NEEDED.** Web is mounted as volume (`./web:/app/web:ro`).
Just refresh browser (`Ctrl+Shift+R` for hard refresh).

### After editing CSS (`web/static/css/...`)
**NO RESTART NEEDED.** Refresh browser.

### Stop work
```bash
make down          # Stop all containers (data preserved)
```

### View logs
```bash
make logs          # All services
make logs-api      # API only
make logs-celery   # Celery worker only
```

### If something is broken
```bash
make restart       # Soft restart (no rebuild)
make rebuild       # Full rebuild (slow)
make prune         # Nuclear option: delete ALL data
```

---

## 7. Backend Development

### Architecture pattern: Clean Architecture

```
Routers (api/*.py)          <- thin: parse request, call service, return response
  -> Services (services/*.py) <- business logic
    -> Repositories (repositories/*.py) <- data access
      -> Models (models/*.py)        <- SQLAlchemy ORM
```

### Adding a new API endpoint
1. Define Pydantic schema in `api/app/schemas/<domain>.py`
2. Add business logic in `api/app/services/<service>.py`
3. Add router in `api/app/api/<domain>.py` (or extend existing)
4. Register router in `api/app/main.py` (if new file)
5. Run `make rebuild-api`

### Adding a new DB table
1. Add SQLAlchemy model in `api/app/models/<model>.py`
2. Add Pydantic schema in `api/app/schemas/<domain>.py`
3. Generate migration: `make revision msg=add_<table>` (use `make shell-api` and alembic manually if needed)
4. Apply: `make migrate`

### Testing the API manually
```bash
# Health
curl http://localhost:8000/health

# Login
curl -X POST http://localhost:8000/admin/auth \
  -H "Content-Type: application/json" \
  -d '{"password":"PassatAdmin!#"}'
# Returns: {"token":"..."}

# Use token
curl http://localhost:8000/databases \
  -H "Authorization: Bearer <token>"
```

---

## 8. Frontend Development

### Critical rule: NO BUILD STEP

The frontend is plain HTML/CSS/JS. No webpack, no React, no npm.
- Edit files in `web/`
- Refresh browser (`Ctrl+Shift+R`)
- Done

### Cache busting convention
When you make breaking JS changes, bump the version in `web/admin.html` and `web/index.html`:
```html
<script src="/static/js/admin.js?v=2.2.0"></script>
```
Also bump CSS:
```html
<link rel="stylesheet" href="/static/css/admin.css?v=4">
```

This forces the browser to fetch the new file instead of using the cached one.

### Backend reads frontend from volume
In `docker-compose.yml`:
```yaml
api:
  volumes:
    - ./web:/app/web:ro
```
This means changes to `web/*` are immediately visible to the running API
without rebuilding the image. Perfect for UI development.

---

## 9. Common Commands Reference

| Command | What it does |
|---|---|
| `make up` | Start all services (6 containers) |
| `make down` | Stop all services |
| `make restart` | Restart (no rebuild) |
| `make ps` | List containers status |
| `make logs` | Tail logs of all services |
| `make logs-api` | Tail API logs only |
| `make shell-api` | Open bash in API container |
| `make shell-postgres` | Open psql CLI |
| `make shell-qdrant` | Open shell in Qdrant container |
| `make migrate` | Apply Alembic migrations |
| `make revision msg=foo` | Create new migration |
| `make rebuild-api` | Rebuild + restart API and Celery (after Python changes) |
| `make rebuild` | Rebuild everything |
| `make backup` | Dump PostgreSQL to `data/backups/` |
| `make backup-full` | Dump PostgreSQL + Qdrant |
| `make restore FILE=path` | Restore from dump |
| `make tunnel-up` | Start Cloudflare Tunnel (needs TUNNEL_TOKEN in .env) |
| `make tunnel-down` | Stop Cloudflare Tunnel |
| `make tunnel-logs` | Tail cloudflared logs |
| `make open-site` | Open http://localhost:8000 in browser |
| `make open-admin` | Open admin panel in browser |
| `make open-flower` | Open Celery Flower (localhost:5555) |
| `make open-docs` | Open docs/README.md |
| `make password NEW=foo` | Change admin password (and rebuild API) |
| `make test` | Run pytest in API container |
| `make lint` | Run ruff check |
| `make format` | Run ruff format |
| `make clean` | Remove __pycache__ |
| `make prune` | **DANGER:** delete all containers + volumes + data |
| `make help` | Show all commands |

**PowerShell equivalents:** `.\make.ps1 up`, `.\make.ps1 logs-api`, etc.

---

## 10. Critical Gotchas (READ THESE)

### 10.1 Pydantic v2 + bcrypt in .env
**Problem:** Pydantic v2's `BaseSettings` interpolates `$VAR` in env files as variables.
**Symptom:** Bcrypt hash `$2b$12$...` gets corrupted to empty string.
**Solution:** Use `@property` with `os.getenv()` instead of declaring as Pydantic field. See `api/app/config.py`:
```python
@property
def admin_password_hash(self) -> str:
    return os.getenv("ADMIN_PASSWORD_HASH", "")
```

### 10.2 Bcrypt escape in Docker Compose
**Problem:** `$` in env file value is interpreted as variable by Docker Compose.
**Solution:** Escape with `$$` in `.env`:
```bash
# In .env:
ADMIN_PASSWORD_HASH=$$2b$$12$$pf0r...
# Each $ becomes $$
```

### 10.3 OpenRouter headers
**Problem:** OpenRouter /rerank returns 403 Forbidden if wrong headers.
**Solution:** Use **X-Title (OLD name)**, NOT X-OpenRouter-Title.
**DO NOT add User-Agent** - OpenRouter's Cloudflare guardrail blocks custom User-Agents.
```python
headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://ksr-matcher.local",
    "X-Title": "KSR Matcher",  # OLD name, NOT X-OpenRouter-Title
    # NO User-Agent header!
}
```

### 10.4 get_db() MUST commit
**Problem:** FastAPI dependency `get_db()` was not committing after PUT requests.
**Symptom:** Saved settings disappeared on next GET.
**Solution:** `get_db()` in `api/app/db/postgres.py` does `await session.commit()` on success:
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_session_maker()() as session:
        try:
            yield session
            await session.commit()  # IMPORTANT
        except Exception:
            await session.rollback()
            raise
```

### 10.5 Session.get() with non-PK column
**Problem:** `AsyncSession.get(Model, "name")` doesn't work — `get()` only takes primary key.
**Solution:** Use `select()` for non-PK lookups:
```python
# WRONG:
return await self.session.get(ApiProvider, name=name)

# CORRECT:
from sqlalchemy import select
result = await self.session.execute(
    select(ApiProvider).where(ApiProvider.name == name)
)
return result.scalars().first()
```

### 10.5.1 Lazy loading in async context (MissingGreenlet)
**Problem:** Accessing `c.materials` after the session closed (or in non-async path) raises `MissingGreenlet`.
**Solution:** Use `selectinload()` to eager-load relations in async:
```python
# WRONG:
result = await session.execute(select(Collection).where(...))
collections = result.scalars().all()
for c in collections:
    count = len(c.materials)  # MissingGreenlet here!

# CORRECT:
from sqlalchemy.orm import selectinload
result = await session.execute(
    select(Collection)
    .where(...)
    .options(selectinload(Collection.materials))
)
collections = result.scalars().all()
for c in collections:
    count = len(c.materials)  # OK - already loaded
```

### 10.6 Qdrant alpine has no wget/curl
**Problem:** Qdrant 1.18+ alpine image doesn't have wget/curl, healthcheck fails.
**Solution:** No healthcheck. Use `condition: service_started` instead of `service_healthy`.

### 10.7 Docker Compose v1 vs v2
**Problem:** User has Docker Compose v5.1.4 (v1 in some places) which doesn't support `--profile`.
**Solution:** Use override files (`docker-compose.cloudflared.yml`) instead of profiles.

### 10.8 Cloudflare Tunnel config
- Service URL inside Docker network: `http://api:8000` (NOT localhost!)
- `TUNNEL_TOKEN` must be in `.env` (not empty)
- Get token from: Cloudflare Dashboard -> Zero Trust -> Networks -> Tunnels

### 10.9 Browser cache for admin.js
**Problem:** After JS changes, browser shows old version with bugs (e.g. "undefined" in inputs).
**Solution:**
- Always bump `?v=X.Y.Z` in HTML script tag
- Add `<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">`
- Tell user to `Ctrl+Shift+R`

### 10.10 PowerShell encoding (CP1251 vs UTF-8)
**Problem:** PowerShell on Windows uses CP1251 by default. Makefile with UTF-8 shows as garbage.
**Solution:**
- `Makefile` is now pure ASCII (no Unicode characters)
- PowerShell profile has `chcp 65001` for UTF-8 (see Gotchas 10.11)

### 10.11 PowerShell profiles
User has TWO PowerShell profiles:
1. PowerShell 7 (pwsh): `C:\Users\klim9\OneDrive\02_Documents\PowerShell\Microsoft.PowerShell_profile.ps1`
2. Windows PowerShell 5 (powershell): `C:\Users\klim9\OneDrive\02_Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`

Both need same snippets (PATH for make, UTF-8 encoding).

---

## 11. Secrets Management

| Secret | Where | How to change |
|---|---|---|
| Admin password | `.env` as bcrypt hash | `make password NEW=foo` |
| OpenRouter API key | DB (encrypted via Fernet) | Through admin panel only |
| JWT secret | `.env` | Manual edit + `make rebuild-api` (all users logged out) |
| Fernet key | `.env` | Manual edit + `make rebuild-api` (encrypted data in DB unreadable!) |
| Postgres password | `.env` + actual DB | Manual edit + `ALTER USER` + `make rebuild` |
| Cloudflare token | `.env` | Manual edit |
| Flower auth | `.env` | Manual edit + `make rebuild` |

**For full details:** see `docs/09-security-secrets.md`

---

## 12. Deployment

### Local (user's PC)
- All commands in `Makefile`
- Cloudflare Tunnel via `make tunnel-up` (after one-time setup in Cloudflare Dashboard)
- Domain: ksrmatch.online (or trycloudflare.com for quick test)

### Production VPS
- See `deploy/hoster-by.md` and `docs/08-deploy-vps.md`
- Same `docker-compose.yml`, just needs production secrets in `.env`
- nginx + Let's Encrypt for HTTPS (optional, can use Cloudflare instead)

---

## 13. UI Refactoring Roadmap (NEXT BIG TASK)

**Status:** UI works but is in technical debt. **admin.js is 4690 lines**, **app.js is 2021 lines**. These are god files with everything in one place.

### Goals
1. **Break down god files** into modules by feature/responsibility
2. **Eliminate global state** (currently `openrouterState`, `materialState`, etc. are globals)
3. **Use modern patterns**: ES6 modules, classes, or at minimum IIFE namespaces
4. **Add proper error handling** (try/catch + user-friendly messages)
5. **Add input validation** (no more "undefined" appearing in fields)
6. **Type safety** (TypeScript? Or JSDoc with @typedef)

### Proposed structure
```
web/static/js/
|-- app.js                  # Main entry, bootstrap
|-- admin.js                # Main entry for admin
|-- core/
|   |-- api.js              # Fetch wrapper (authFetch)
|   |-- dom.js              # DOM helpers
|   |-- state.js            # Application state container
|   |-- events.js           # Event bus (or use simple pub/sub)
|-- features/
|   |-- search/
|   |   |-- index.js
|   |   |-- results.js
|   |   `-- filters.js
|   |-- collections/
|   |   |-- list.js
|   |   `-- detail.js
|   |-- import/
|   |   |-- upload.js
|   |   `-- progress.js
|   |-- settings/
|   |   |-- llm-api.js
|   |   |-- statuses.js
|   |   `-- cleaning-rules.js
|   |-- feedback/
|   `-- jobs/
|-- ui/
    |-- modal.js
    |-- toast.js
    `-- status-indicator.js
```

### Approach
1. **Start with the most painful section** - the LLM API settings card (the most recently modified)
2. **Extract one feature at a time** (vertical slicing)
3. **Maintain backward compat** - keep `admin.js` as entry, but progressively move code to modules
4. **Add tests** if possible (jsdom + jest? or just smoke tests)
5. **Document module boundaries** in AGENTS.md or in `web/static/js/README.md`

### Constraints
- **NO build step** - keep using plain JS + ES modules (or IIFE)
- **No npm** - load directly via `<script type="module">`
- **Keep works as-is** - every refactor step must keep admin working

---

## 14. Known Issues / TODO

### Bugfixes done (don't redo)
- "undefined" in LLM API settings fields (cache-busting fix)
- 403 on OpenRouter /rerank (use X-Title old, no User-Agent)
- get_db() not committing
- Session.get() with non-PK
- bcrypt interpolation in .env
- Qdrant no healthcheck

### Pending improvements
- [ ] UI refactoring (Section 13)
- [ ] pytest tests (currently none)
- [ ] CI/CD (currently manual)
- [ ] HTTPS via nginx (using Cloudflare for now)
- [ ] Historical JSONL feedback migration (decision: not needed, was old format)
- [ ] BM25: in-memory, OK for 150k records, not for 1M+

---

## 15. Communication Style

When responding to the user:
- **Answer in Russian** (user writes in Russian)
- **Be concise** - no unnecessary preamble
- **One command = one line** when possible
- **Show actual outputs** when debugging
- **If something is broken, fix it** - don't ask permission for obvious fixes
- **If user is wrong, say so politely** - user appreciates honesty
- **Don't use emojis** (user doesn't ask for them, and they break in CP1251)

When committing:
- Use English commit messages
- Format: `<type>(scope): short description`
- Types: feat, fix, docs, refactor, test, chore
- Add a body explaining what and why

When something doesn't work:
- Check `make logs-api` first
- Check if migration was applied (`make migrate`)
- Check if user forgot `make rebuild-api` after Python change
- Check if browser needs hard refresh (Ctrl+Shift+R) after JS change

---

## 16. If You Need Help (Context You Don't Have)

If user asks something you can't figure out from this file:
1. Read `docs/README.md` for topic-specific docs
2. Read `docs/09-security-secrets.md` for secrets
3. Read `docs/06-tunnel.md` for Cloudflare
4. Read `docs/08-deploy-vps.md` for VPS
5. If still unclear, ask user - but ONLY if it's truly project-specific knowledge you can't infer

**Things you SHOULD NOT ask the user:**
- "What is the admin password?" - it's `PassatAdmin!#`
- "How do I start the server?" - see Section 2
- "What port does X run on?" - see Section 4
- "How do I change the API key?" - through admin panel
- "How do I rebuild after Python changes?" - `make rebuild-api`
- "How do I open admin?" - `make open-admin`

**Things you MAY ask the user:**
- "What's your Cloudflare TUNNEL_TOKEN?" - they need to provide
- "What specific URL/domain do you want for the tunnel?" - they need to decide
- "What should the new password be?" - they need to choose

---

## 17. Quick Reference Card

```
# Start everything
make up && make migrate

# After Python changes
make rebuild-api

# After UI changes - just refresh browser (Ctrl+Shift+R)

# View logs
make logs-api

# Open admin
make open-admin
# Login: admin / PassatAdmin!#

# Stop
make down
```

**If in doubt: `make help` shows all commands.**

**Last updated:** 2026-06-11 (refactor/v2-clean-architecture)
