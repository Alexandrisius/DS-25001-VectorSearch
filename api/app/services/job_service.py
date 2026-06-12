"""JobService — управление фоновыми задачами (CRUD)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.background_job import BackgroundJob, JobStatus


class JobService:
    """CRUD для фоновых задач."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, job_type: str, params: dict[str, Any] | None = None) -> BackgroundJob:
        job = BackgroundJob(
            id=uuid.uuid4(),
            type=job_type,
            status=JobStatus.PENDING.value,
            params=params or {},
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> BackgroundJob | None:
        return await self.session.get(BackgroundJob, uuid.UUID(job_id))

    async def list_all(self, limit: int = 50) -> list[BackgroundJob]:
        result = await self.session.execute(
            select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def update(self, job_id: str, **fields: Any) -> None:
        job = await self.get(job_id)
        if not job:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        await self.session.flush()

    async def cancel(self, job_id: str) -> bool:
        job = await self.get(job_id)
        if job and job.status in (JobStatus.PENDING.value, JobStatus.PROCESSING.value):
            job.status = JobStatus.CANCELLED.value
            job.finished_at = datetime.now(timezone.utc)
            await self.session.flush()
            return True
        return False


__all__ = ["JobService"]
