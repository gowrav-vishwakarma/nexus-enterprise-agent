"""Optional Honcho memory provider. Import the vendor SDK only at call time."""

from __future__ import annotations

from typing import Any, Optional

from nexus.config.memory import MemoryConfig
from nexus.tools.context import RunContext


class HonchoMemoryProvider:
    """Bridge to the Honcho Dialectic API, scoped by ``RunContext``.

    Not a required dependency. Pass a ready ``client`` in tests.
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
                from honcho import Honcho  # type: ignore
            except ImportError as exc:
                raise ImportError(
                    "HonchoMemoryProvider needs the honcho package. "
                    "Install it separately; it is not a Nexus required dependency."
                ) from exc
            self._client = Honcho(**self._client_kwargs)
        return self._client

    def _session_key(self, ctx: RunContext) -> str:
        return f"{ctx.tenant_id or '_'}:{ctx.user_id or '_'}:{self._config.namespace or 'default'}"

    async def prefetch(self, ctx: RunContext) -> dict[str, str]:
        hits = await self.search(ctx, query="", k=self._config.max_entities)
        return {str(h.get("key", i)): str(h.get("value", "")) for i, h in enumerate(hits)}

    async def search(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        client = self._get_client()
        dialectic = getattr(client, "dialectic", None) or getattr(client, "search", None)
        if dialectic is None:
            return []
        raw = dialectic(query or " ", session_id=self._session_key(ctx), limit=k)
        if hasattr(raw, "__await__"):
            raw = await raw
        items = raw if isinstance(raw, list) else (raw.get("results") if isinstance(raw, dict) else [])
        out: list[dict[str, Any]] = []
        for item in items or []:
            if isinstance(item, dict):
                text = item.get("content") or item.get("message") or item.get("text") or ""
                out.append(
                    {
                        "key": str(item.get("id") or text[:40]),
                        "value": str(text),
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
        add = getattr(client, "add", None) or getattr(client, "write", None)
        if callable(add):
            result = add(f"{key}: {value}", session_id=self._session_key(ctx))
            if hasattr(result, "__await__"):
                await result

    async def remove(
        self, ctx: RunContext, key: str, store: str = "default"
    ) -> None:
        del store, ctx
        client = self._get_client()
        delete = getattr(client, "delete", None)
        if callable(delete):
            result = delete(key)
            if hasattr(result, "__await__"):
                await result

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
