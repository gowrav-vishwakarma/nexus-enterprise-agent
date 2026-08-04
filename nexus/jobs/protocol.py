"""Job scheduling protocol."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from nexus.tools.context import RunContext

JobDeliveryCallback = Callable[[RunContext, dict[str, Any]], Awaitable[None]]


@runtime_checkable
class JobStore(Protocol):
    async def list_jobs(self) -> list[dict[str, Any]]: ...
    async def save_job(self, job: dict[str, Any]) -> None: ...
    async def delete_job(self, job_id: str) -> None: ...
