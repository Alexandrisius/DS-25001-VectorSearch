# Gotchas (10.1 — 10.18)

The seven **critical** gotchas are duplicated in the root `AGENTS.md`
Section 5 (because they are non-obvious and will burn you without
warning). This file is the **full reference** with code samples and
context for all gotchas encountered so far.

## 10.1 bcrypt interpolation in .env
**Problem:** `$$` in bash and docker-compose is special.
**Solution:** escape with `$$` so it survives interpolation.

## 10.2 Fernet key rotation
**Problem:** changing `ENCRYPTION_KEY` makes all encrypted data unreadable.
**Solution:** never rotate without decrypting and re-encrypting first.

## 10.3 OpenRouter headers
**Problem:** OpenRouter /rerank returns 403 if missing headers.
**Solution:** use **all four** (X-Title, HTTP-Referer, User-Agent, Authorization).
X-Title is the OLD name (not X-OpenRouter-Title). User-Agent MUST be
custom — default `python-httpx/x.x.x` is blocked by Cloudflare guardrail.
```python
headers = {
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "User-Agent": "KSR-Matcher/2.0",
    "HTTP-Referer": "https://ksrmatch.online/",
    "X-Title": "KSR Matcher",
}
```

## 10.4 get_db() MUST commit
**Problem:** FastAPI dep `get_db()` was not committing after PUT.
**Symptom:** Saved settings disappeared on next GET.
**Solution:** `get_db()` in `api/app/db/postgres.py` does `await session.commit()`.

## 10.5 Session.get() with non-PK column
**Solution:** use `select()` for non-PK lookups (get() only takes PK).

## 10.5.1 Lazy loading in async context (MissingGreenlet)
**Solution:** `selectinload()` for relations in async. Or pass `record_count`
explicitly to `to_dict()` (see `Collection.to_dict(record_count=...)`).

## 10.6 Qdrant alpine has no wget/curl
**Solution:** no healthcheck. Use `condition: service_started` not
`service_healthy` in docker-compose.

## 10.7 Docker Compose v1 vs v2
User has Docker Compose v5.1.4. Use override files
(`docker-compose.cloudflared.yml`) instead of profiles.

## 10.8 Cloudflare Tunnel config
- Service URL inside Docker: `http://api:8000` (NOT localhost)
- `TUNNEL_TOKEN` must be in `.env`

## 10.9 Browser cache for admin.js
- Bump `?v=X.Y.Z` in HTML
- `Ctrl+Shift+R` for hard refresh

## 10.10 PowerShell encoding (CP1251 vs UTF-8)
**Solution:** Makefile is pure ASCII. PowerShell profile has `chcp 65001`.

## 10.11 PowerShell profiles (two of them)
PowerShell 7 (`pwsh`) and Windows PowerShell 5 (`powershell`) have
separate profiles. Both need same snippets.

## 10.12 Qdrant gRPC instead of HTTP (32 MB hard limit)
**Problem:** Qdrant HTTP API has 32 MB hardcoded payload limit.
142k codes via MatchAny = 90 MB > limit.
**Solution:**
```python
QdrantClient(
    prefer_grpc=True,
    grpc_port=6334,
    grpc_options={'grpc.max_message_length': 100 * 1024 * 1024},
)
```
In `docker-compose.yml`:
```yaml
environment:
  QDRANT__SERVICE__GRPC_PORT: 6334
ports:
  - "6333:6333"
  - "6334:6334"
```

## 10.13 Folder rebuild MUST use bulk embed
**Problem:** 1500-3000 folders. `embed_one` in loop = 30+ min sequential HTTP.
UI shows "89% stuck" because progress isn't updated during folder phase.
**Solution:** one `embed_batch(folder_paths, progress_cb=...)`. Then collect
all `qm.PointStruct` and one `qdrant.upsert(points=points)`.
Update `job.progress` in `progress_cb` (92→99%) with 500ms throttling.

## 10.14 Worker cancellation pattern
**Problem:** `JobService.cancel()` sets `status=CANCELLED` in БД, but
worker doesn't check it. `tasks.py` also re-sets `status=COMPLETED`
overwriting CANCELLED.
**Solution:**
1. Helper `async def _is_cancelled(session, job)` — `session.expire(job)` +
   `session.get(BackgroundJob, job.id)` for fresh SELECT.
2. Check in: chunked loop, before `embed_batch`, before `qdrant.upsert`,
   in final completion block.
3. **tasks.py MUST NOT re-set `status=COMPLETED`** after `import_records`.
4. Return `{"cancelled": True}` from `import_records`.

## 10.15 Stored counters in collections
**Problem:** `SELECT COUNT(*) ...` on 142k records = 2-3 sec lag.
**Solution:**
- Alembic 0003 adds `collections.materials_count Integer NOT NULL DEFAULT 0`
- Backfill: `UPDATE...FROM (SELECT collection_id, COUNT(*)...)`
- `_upsert_materials_bulk` increments: `collection.materials_count += len(chunk)`
- `/admin/collections` reads `c.materials_count` (instant).
- Fallback to COUNT(*) only if all counters are 0.

## 10.16 Alembic migration: rebuild-api BEFORE migrate
**Problem:** `api` service is built from `./api` context (no volume
mount for Python). New migration file in `./api/alembic/versions/`
is not in the running container.
**Solution:**
1. `make rebuild-api` — copies new file into image
2. `make migrate` — alembic upgrade head sees the file

## 10.17 Async auth: show splash, NOT login form
**Problem:** `initAuth()` async `validateToken()` shows login form for
100-500ms ("auth flash").
**Solution:** hide `loginScreen` by default, show `<div id="authSplash">`
spinner. `initAuth()` keeps splash visible while Promise resolves.
`showApp()` hides BOTH splash and login.

## 10.18 pg_insert counter caveat
**Problem:** `materials_count += len(chunk)` on every chunk — but
`ON CONFLICT DO UPDATE` means same code re-import just updates, but
counter still increments. Repeated imports → counter overcount.
**Solution:** for exact counter, use `WHERE NOT EXISTS` in pg_insert, or
reset `collection.materials_count = 0` before each import.
