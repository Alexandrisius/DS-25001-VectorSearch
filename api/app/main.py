"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    admin,
    admin_data,
    collections,
    feedback,
    hierarchy,
    import_export,
    materials,
    search,
    settings as settings_api,
    system,
)
from app.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import logger, setup_logging
from app.core.middleware import RequestContextMiddleware
from app.db.postgres import close_db
from app.db.qdrant import close_qdrant
from app.db.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown hooks."""
    setup_logging()
    settings = get_settings()
    logger.info(f"🚀 KSR Vector Search v2 starting (env={settings.env})")

    # Web директория — as-is, монтируется через docker volume ./web:/app/web
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
        logger.info(f"✅ Static files mounted from {web_dir}")
    else:
        logger.warning(f"⚠️ web/ not found at {web_dir}")

    yield

    logger.info("🛑 Shutting down...")
    await close_db()
    await close_redis()
    close_qdrant()
    logger.info("👋 Stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="KSR Matcher API v2",
        description="Семантический поиск по КСР (Qdrant + OpenRouter)",
        version="2.0.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Request ID + logging
    app.add_middleware(RequestContextMiddleware)
    # Exception handlers
    register_exception_handlers(app)

    # Routers
    app.include_router(system.router)
    app.include_router(search.router)
    app.include_router(hierarchy.router)
    app.include_router(feedback.router)
    app.include_router(materials.router)
    app.include_router(collections.router)
    app.include_router(admin.router)
    app.include_router(admin_data.router)
    app.include_router(settings_api.router)
    app.include_router(import_export.router)

    # Web UI (HTML)
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def root() -> str:
        web_index = Path(__file__).resolve().parent.parent / "web" / "index.html"
        if web_index.exists():
            return web_index.read_text(encoding="utf-8")
        return "<h1>KSR Matcher v2</h1><p>web/index.html not found</p>"

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def admin_page() -> str:
        web_admin = Path(__file__).resolve().parent.parent / "web" / "admin.html"
        if web_admin.exists():
            return web_admin.read_text(encoding="utf-8")
        return "<h1>Admin</h1><p>web/admin.html not found</p>"

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        workers=1,
        loop="asyncio",
        log_level=settings.log_level.lower(),
    )
