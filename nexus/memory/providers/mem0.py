"""Optional Mem0 memory provider. Import the vendor SDK only at call time."""

from __future__ import annotations

from typing import Any, Optional

from nexus.config.memory import MemoryConfig
from nexus.tools.context import RunContext


class Mem0MemoryProvider:
    """Bridge to the Mem0 client, scoped by tenant / user on ``RunContext``.

    Not a required dependency. Pass a ready ``client`` in tests, or install
    ``mem0ai`` and let the provider construct one on first use.
    """

    def __init__(
        self,
        *,
        client: Any = None,
        config: Optional[MemoryConfig] = None,
        **client_kwargs: Any,
    ):
        self._client = client
        self._client_kwargs = client_kwargs
        self._config = config or MemoryConfig()

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from mem0 import Memory  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "Mem0MemoryProvider needs the mem0ai package. "
                    "Install it separately; it is not a Nexus required dependency."
                ) from exc
            self._client = Memory(**self._client_kwargs)
        return self._client

    def _filters(self, ctx: RunContext) -> dict[str, Any]:
        return {
            "user_id": ctx.user_id or "",
            "metadata": {
                "tenant_id": ctx.tenant_id,
                "company_id": ctx.company_id,
                "namespace": self._config.namespace,
            },
        }

    async def prefetch(self, ctx: RunContext) -> dict[str, str]:
        hits = await self.search(ctx, query="", k=self._config.max_entities)
        return {str(h.get("key", i)): str(h.get("value", "")) for i, h in enumerate(hits)}

    async def search(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        client = self._get_client()
        filters = self._filters(ctx)
        raw = client.search(query or " ", user_id=filters["user_id"], limit=k)
        results = raw.get("results", raw) if isinstance(raw, dict) else raw
        out: list[dict[str, Any]] = []
        for item in results or []:
            if isinstance(item, dict):
                memory = item.get("memory") or item.get("text") or ""
                out.append(
                    {
                        "key": str(item.get("id") or item.get("key") or memory[:40]),
                        "value": str(memory),
                        "store": "default",
                    }
                )
            else:
                out.append({"key": str(item), "value": str(item), "store": "default"})
        return out[:k]

    async def write(
        self, ctx: RunContext, key: str, value: str, store: str = "default"
    ) -> None:
        del store
        client = self._get_client()
        filters = self._filters(ctx)
        client.add(
            f"{key}: {value}",
            user_id=filters["user_id"],
            metadata=filters["metadata"],
        )

    async def remove(
        self, ctx: RunContext, key: str, store: str = "default"
    ) -> None:
        del store
        client = self._get_client()
        delete = getattr(client, "delete", None)
        if callable(delete):
            delete(key)

    async def list_stores(self, ctx: RunContext) -> list[str]:
        del ctx
        return ["default"]

    async def curate(
        self, ctx: RunContext, turn_summary: str
    ) -> dict[str, str]:
        if not turn_summary.strip():
            return {}
        await self.write(ctx, "last_turn", turn_summary[:500])
        return {"last_turn": turn_summary[:500]}
