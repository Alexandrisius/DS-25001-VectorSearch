"""Settings API — /admin/statuses, /admin/cleaning_rules, /admin/openrouter-settings."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.deps import DBSession, get_current_admin
from app.schemas.settings import (
    ApiProviderOut,
    ApiProviderUpdate,
    CleaningRuleOut,
    CleaningRuleUpdate,
    StatusConfigOut,
    StatusesUpdateRequest,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/admin", tags=["admin-settings"])


# ---------------------------------------------------------------- statuses
@router.get("/statuses")
async def get_statuses(session: DBSession) -> dict:
    """Публичный endpoint (без auth) — для загрузки в UI."""
    svc = SettingsService(session)
    statuses = await svc.list_statuses()
    default = await svc.get_default_status()
    return {
        "statuses": [
            {
                "id": s.id,
                "label": s.label,
                "color": s.color,
            }
            for s in statuses
        ],
        "default_status": default.id if default else "active",
    }


@router.put("/statuses", dependencies=[Depends(get_current_admin)])
async def update_statuses(
    req: StatusesUpdateRequest, session: DBSession
) -> dict:
    svc = SettingsService(session)
    updated = await svc.update_statuses(
        [s.model_dump() for s in req.statuses], default_id=req.default_status
    )
    return {
        "status": "success",
        "statuses": [
            StatusConfigOut(
                id=s.id,
                label=s.label,
                color=s.color,
                is_default=s.is_default,
                sort_order=s.sort_order,
            ).model_dump()
            for s in updated
        ],
        "default_status": req.default_status,
    }


# -------------------------------------------------------- cleaning_rules
@router.get("/cleaning_rules")
async def get_cleaning_rules(session: DBSession) -> dict:
    """Публичный."""
    svc = SettingsService(session)
    rules = await svc.list_cleaning_rules()
    return {
        "rules": [
            CleaningRuleOut(
                id=r.id,
                name=r.name,
                pattern=r.pattern,
                replacement=r.replacement,
                enabled=r.enabled,
                apply_to_columns=r.apply_to_columns,
                sort_order=r.sort_order,
            ).model_dump()
            for r in rules
        ]
    }


@router.put("/cleaning_rules", dependencies=[Depends(get_current_admin)])
async def update_cleaning_rules(
    rules: list[CleaningRuleUpdate], session: DBSession
) -> dict:
    # Валидация regex
    for r in rules:
        try:
            re.compile(r.pattern)
        except re.error as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Невалидный regex в '{r.name}': {e}",
            )
    svc = SettingsService(session)
    updated = await svc.update_cleaning_rules([r.model_dump() for r in rules])
    return {
        "status": "success",
        "rules": [
            CleaningRuleOut(
                id=r.id,
                name=r.name,
                pattern=r.pattern,
                replacement=r.replacement,
                enabled=r.enabled,
                apply_to_columns=r.apply_to_columns,
                sort_order=r.sort_order,
            ).model_dump()
            for r in updated
        ],
    }


# --------------------------------------------------------- openrouter
@router.get("/openrouter-settings")
async def get_openrouter_settings(session: DBSession) -> dict:
    """Публичный (маскированный ключ)."""
    svc = SettingsService(session)
    prov = await svc.get_provider("openrouter")
    if not prov:
        return {
            "enabled": False,
            "api_key": "",
            "api_key_set": False,
            "base_url": "",
            "model_embed": "qwen/qwen3-embedding-4b",
            "model_rerank": "cohere/rerank-4-pro",
            "batch_size": 10,
            "max_workers": 3,
        }
    from app.core.security import decrypt_secret
    plain = decrypt_secret(prov.api_key_encrypted) if prov.api_key_encrypted else ""
    return {
        "enabled": prov.enabled,
        "api_key": svc.mask_api_key(plain),
        "api_key_set": bool(prov.api_key_encrypted),
        "base_url": prov.base_url or "",
        "model_embed": prov.model_embed,
        "model_rerank": prov.model_rerank,
        "batch_size": prov.batch_size,
        "max_workers": prov.max_workers,
    }


@router.put("/openrouter-settings", dependencies=[Depends(get_current_admin)])
async def update_openrouter_settings(
    req: ApiProviderUpdate, session: DBSession
) -> dict:
    svc = SettingsService(session)
    prov = await svc.update_provider(
        "openrouter",
        enabled=req.enabled,
        api_key=req.api_key or None,
        base_url=req.base_url,
        model_embed=req.model_embed,
        model_rerank=req.model_rerank,
        batch_size=req.batch_size,
        max_workers=req.max_workers,
    )
    return {
        "status": "success",
        "enabled": prov.enabled,
        "base_url": prov.base_url or "",
        "model_embed": prov.model_embed,
        "model_rerank": prov.model_rerank,
        "batch_size": prov.batch_size,
        "max_workers": prov.max_workers,
        "api_key_set": bool(prov.api_key_encrypted),
    }


@router.post("/openrouter-test", dependencies=[Depends(get_current_admin)])
async def test_openrouter(session: DBSession) -> dict:
    """Тест подключения к эмбеддинг endpoint.

    Использует кастомный base_url если указан, иначе OpenRouter.
    """
    import httpx
    from app.core.security import decrypt_secret
    from app.services.embedding_service import _resolve_embed_url

    svc = SettingsService(session)
    prov = await svc.get_provider("openrouter")
    if not prov or not prov.api_key_encrypted:
        return {"status": "error", "message": "API ключ не настроен"}
    api_key = decrypt_secret(prov.api_key_encrypted)
    endpoint = _resolve_embed_url(prov.base_url)
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if not prov.base_url:
            headers["HTTP-Referer"] = "https://ksr-matcher.local"
            headers["X-Title"] = "KSR Matcher"

        payload: dict = {"model": prov.model_embed, "input": "test connection"}
        if not prov.base_url or "openrouter.ai" in prov.base_url:
            payload["encoding_format"] = "float"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, headers=headers, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            if "error" in data:
                return {"status": "error", "message": data["error"].get("message", "Error")}
            if "data" in data and data["data"]:
                dim = len(data["data"][0].get("embedding", []))
                return {
                    "status": "success",
                    "message": f"OK! Размерность: {dim}",
                }
            return {"status": "error", "message": "Неожиданный формат ответа"}
        if resp.status_code == 401:
            return {"status": "error", "message": "Неверный API ключ"}
        if resp.status_code == 404:
            return {"status": "error", "message": f"Endpoint не найден: {endpoint}"}
        return {
            "status": "error",
            "message": f"Ошибка API ({resp.status_code}): {resp.text[:200]}",
        }
    except httpx.TimeoutException:
        return {"status": "error", "message": "Таймаут подключения"}
    except httpx.ConnectError as e:
        return {"status": "error", "message": f"Не удалось подключиться: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка: {e}"}


@router.get("/embedding_dimension", dependencies=[Depends(get_current_admin)])
async def get_embedding_dimension(session: DBSession) -> dict:
    from app.services.embedding_service import EmbeddingService
    svc = SettingsService(session)
    prov = await svc.get_active_provider() or await svc.get_provider("openrouter")
    if not prov:
        return {"dimension": 2560, "provider": "unknown", "model": "default"}
    dim = EmbeddingService.known_dimension(prov.model_embed) or 2560
    return {
        "dimension": dim,
        "provider": "openrouter" if prov.enabled else "local",
        "model": prov.model_embed,
    }
