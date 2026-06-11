"""SettingsService — управление api_providers, statuses, cleaning_rules."""
from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.security import decrypt_secret, encrypt_secret
from app.models.api_provider import ApiProvider
from app.models.cleaning_rule import CleaningRule
from app.models.status import Status


class SettingsService:
    """CRUD для настроек: провайдеры, статусы, правила очистки."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------- ApiProvider ----------
    async def list_providers(self) -> list[ApiProvider]:
        result = await self.session.execute(select(ApiProvider).order_by(ApiProvider.name))
        return list(result.scalars().all())

    async def get_provider(self, name: str) -> ApiProvider | None:
        return await self.session.get(ApiProvider, name=name)  # type: ignore[arg-type]

    async def get_or_create_provider(self, name: str) -> ApiProvider:
        prov = await self.get_provider(name)
        if prov:
            return prov
        prov = ApiProvider(name=name)
        self.session.add(prov)
        await self.session.flush()
        return prov

    async def get_active_provider(self) -> ApiProvider | None:
        """Возвращает enabled провайдер, либо None."""
        result = await self.session.execute(
            select(ApiProvider).where(ApiProvider.enabled == True)  # noqa: E712
        )
        return result.scalars().first()

    async def update_provider(
        self,
        name: str,
        *,
        enabled: bool | None = None,
        api_key: str | None = None,
        model_embed: str | None = None,
        model_rerank: str | None = None,
        batch_size: int | None = None,
        max_workers: int | None = None,
    ) -> ApiProvider:
        prov = await self.get_or_create_provider(name)
        if enabled is not None:
            prov.enabled = enabled
        if api_key and "*" not in api_key:
            prov.api_key_encrypted = encrypt_secret(api_key)
        if model_embed is not None:
            prov.model_embed = model_embed
        if model_rerank is not None:
            prov.model_rerank = model_rerank
        if batch_size is not None:
            prov.batch_size = batch_size
        if max_workers is not None:
            prov.max_workers = max_workers
        await self.session.flush()
        return prov

    def mask_api_key(self, key: str) -> str:
        if not key:
            return ""
        if len(key) <= 4:
            return "*" * len(key)
        return "*" * (len(key) - 4) + key[-4:]

    # ---------- Statuses ----------
    async def list_statuses(self) -> list[Status]:
        result = await self.session.execute(
            select(Status).order_by(Status.sort_order, Status.id)
        )
        return list(result.scalars().all())

    async def get_default_status(self) -> Status | None:
        result = await self.session.execute(select(Status).where(Status.is_default == True))  # noqa: E712
        return result.scalars().first()

    async def update_statuses(
        self, statuses: list[dict[str, Any]], default_id: str
    ) -> list[Status]:
        # Удалить все старые
        existing = await self.list_statuses()
        for s in existing:
            await self.session.delete(s)
        await self.session.flush()

        # Создать новые
        ids = {s["id"] for s in statuses}
        if default_id not in ids:
            raise NotFoundError(f"default_status '{default_id}' не найден в списке")
        for i, s in enumerate(statuses):
            self.session.add(
                Status(
                    id=s["id"],
                    label=s["label"],
                    color=s["color"],
                    is_default=(s["id"] == default_id),
                    sort_order=(i + 1) * 10,
                )
            )
        await self.session.flush()
        return await self.list_statuses()

    # ---------- Cleaning rules ----------
    async def list_cleaning_rules(self) -> list[CleaningRule]:
        result = await self.session.execute(
            select(CleaningRule).order_by(CleaningRule.sort_order, CleaningRule.id)
        )
        return list(result.scalars().all())

    async def update_cleaning_rules(self, rules: list[dict[str, Any]]) -> list[CleaningRule]:
        existing = await self.list_cleaning_rules()
        for r in existing:
            await self.session.delete(r)
        await self.session.flush()

        for i, r in enumerate(rules):
            self.session.add(
                CleaningRule(
                    name=r.get("name"),
                    pattern=r["pattern"],
                    replacement=r.get("replacement", ""),
                    enabled=r.get("enabled", True),
                    apply_to_columns=r.get("apply_to_columns", ["*"]),
                    sort_order=r.get("sort_order", (i + 1) * 10),
                )
            )
        await self.session.flush()
        return await self.list_cleaning_rules()


__all__ = ["SettingsService"]
