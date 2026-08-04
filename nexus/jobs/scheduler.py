"""Reference in-memory job scheduler."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from nexus.jobs.protocol import JobStore
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)


@dataclass
class ScheduledJob:
    id: str
    cron: str
    prompt: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


def _job_to_dict(job: ScheduledJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "cron": job.cron,
        "prompt": job.prompt,
        "enabled": job.enabled,
        "metadata": job.metadata,
    }


def _job_from_dict(raw: dict[str, Any]) -> ScheduledJob:
    return ScheduledJob(
        id=raw["id"],
        cron=raw["cron"],
        prompt=raw["prompt"],
        enabled=raw.get("enabled", True),
        metadata=raw.get("metadata") or {},
    )


class InMemoryJobStore:
    """Simple job store for development."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    async def list_jobs(self) -> list[dict[str, Any]]:
        return list(self._jobs.values())

    async def save_job(self, job: dict[str, Any]) -> None:
        self._jobs[job["id"]] = job

    async def delete_job(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


class JobScheduler:
    """Minimal scheduler that fires due jobs on an interval loop.

    Nexus does not ship a cron parser. Pass ``is_due`` to plug in your own
    (``croniter``, APScheduler, or a database column); the default fires every
    enabled job on every tick, which is only useful for development.
    """

    def __init__(
        self,
        store: JobStore,
        *,
        run_factory: Callable[[ScheduledJob], Awaitable[None]],
        is_due: Optional[Callable[[ScheduledJob, datetime], bool]] = None,
    ):
        self.store = store
        self.run_factory = run_factory
        self.is_due = is_due or (lambda job, now: True)
        self._task: Optional[asyncio.Task] = None

    async def add_job(self, cron: str, prompt: str, **metadata: Any) -> ScheduledJob:
        job = ScheduledJob(
            id=str(uuid.uuid4()),
            cron=cron,
            prompt=prompt,
            metadata=metadata,
        )
        await self.store.save_job(_job_to_dict(job))
        return job

    async def run_due_jobs(self, now: Optional[datetime] = None) -> list[ScheduledJob]:
        """Run every enabled job that ``is_due`` accepts; return the jobs fired."""
        moment = now or datetime.now(timezone.utc)
        fired: list[ScheduledJob] = []
        for raw in await self.store.list_jobs():
            job = _job_from_dict(raw)
            if not job.enabled or not self.is_due(job, moment):
                continue
            await self.run_factory(job)
            fired.append(job)
        return fired

    def start_background(self, interval_seconds: float = 60.0) -> None:
        async def _loop() -> None:
            while True:
                try:
                    await self.run_due_jobs()
                except Exception as exc:
                    logger.warning("JobScheduler tick failed: %s", exc)
                await asyncio.sleep(interval_seconds)

        self._task = asyncio.create_task(_loop())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()


def build_cron_run_context(base: RunContext, job: ScheduledJob) -> RunContext:
    """Build a non-persistable cron RunContext from a base context."""
    return RunContext(
        tenant_id=base.tenant_id,
        company_id=base.company_id,
        user_id=base.user_id,
        session_id=f"cron_{job.id}",
        is_cron=True,
        metadata={**base.metadata, "job_id": job.id, "prompt": job.prompt},
    )
