"""Memory provider protocol for pluggable external stores."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nexus.tools.context import RunContext


@runtime_checkable
class MemoryProviderProtocol(Protocol):
    """Optional external memory backend."""

    async def prefetch(self, ctx: RunContext) -> dict[str, str]: ...
    async def sync_turn(self, ctx: RunContext, turn_summary: str) -> None: ...
    def tool_schemas(self) -> list[dict[str, Any]]: ...
