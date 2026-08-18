"""Memory provider protocol for pluggable external stores."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nexus.tools.context import RunContext


@runtime_checkable
class MemoryProvider(Protocol):
    """Optional richer memory backend (semantic search, external vendors, HITL).

    When ``MemoryConfig.provider`` is unset, the runner keeps using
    ``CrossSessionMemoryStore`` directly so existing apps (including a custom
    store passed as ``cross_session_memory_store=``) need no changes.
    """

    async def prefetch(self, ctx: RunContext) -> dict[str, str]: ...

    async def search(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[dict[str, Any]]: ...

    async def write(
        self, ctx: RunContext, key: str, value: str, store: str = "default"
    ) -> None: ...

    async def remove(
        self, ctx: RunContext, key: str, store: str = "default"
    ) -> None: ...

    async def list_stores(self, ctx: RunContext) -> list[str]: ...

    async def curate(
        self, ctx: RunContext, turn_summary: str
    ) -> dict[str, str]: ...


# Deprecated alias — kept for one release so ``from nexus.memory.provider import
# MemoryProviderProtocol`` still works.
MemoryProviderProtocol = MemoryProvider
