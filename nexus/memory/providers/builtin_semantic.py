"""Built-in semantic memory provider wrapping CrossSessionMemoryStore."""

from __future__ import annotations

from typing import Any, Optional

from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    resolve_cross_session_namespace,
)
from nexus.tools.context import RunContext


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().split() if t}


class BuiltInSemanticMemoryProvider:
    """KV facts plus token-overlap search. No extra dependencies.

    Wraps the existing ``CrossSessionMemoryStore`` so ``TenantMemoryStore`` and
    the SQLite/Postgres/Redis stores keep working unchanged.
    """

    def __init__(
        self,
        store: Optional[CrossSessionMemoryStore] = None,
        config: Optional[MemoryConfig] = None,
        *,
        agent_name: str = "",
        **_: Any,
    ):
        if store is None:
            raise ValueError("BuiltInSemanticMemoryProvider requires a CrossSessionMemoryStore")
        self._store = store
        self._config = config or MemoryConfig()
        self._agent_name = agent_name

    def _base_namespace(self) -> str:
        return resolve_cross_session_namespace(self._config.namespace, self._agent_name)

    def _namespace(self, store: str = "default") -> str:
        base = self._base_namespace()
        if store and store not in ("default",):
            return f"{base}:{store}"
        return base

    def _store_names(self) -> list[str]:
        if self._config.stores:
            names = [s.name for s in self._config.stores]
        else:
            names = ["default"]
        if self._config.require_approval and "pending" not in names:
            names = [*names, "pending"]
        return names

    async def prefetch(self, ctx: RunContext) -> dict[str, str]:
        if not ctx.user_id:
            return {}
        stores = list(self._config.stores)
        if not stores:
            record = await self._store.load(
                ctx.tenant_id,
                ctx.user_id,
                self._namespace("default"),
                company_id=ctx.company_id,
            )
            return dict(record.entity_memory) if record else {}
        always = [s for s in stores if s.inject == "always"]
        multi = len(always) > 1
        merged: dict[str, str] = {}
        for store_cfg in always:
            record = await self._store.load(
                ctx.tenant_id,
                ctx.user_id,
                self._namespace(store_cfg.name),
                company_id=ctx.company_id,
            )
            if not record or not record.entity_memory:
                continue
            for key, value in record.entity_memory.items():
                out_key = f"{store_cfg.name}/{key}" if multi else key
                merged[out_key] = value
        return merged

    async def search(
        self, ctx: RunContext, query: str, k: int = 5
    ) -> list[dict[str, Any]]:
        if not ctx.user_id:
            return []
        q_tokens = _tokens(query)
        q_lower = query.lower()
        matches: list[tuple[float, dict[str, Any]]] = []
        for name in self._store_names():
            record = await self._store.load(
                ctx.tenant_id,
                ctx.user_id,
                self._namespace(name),
                company_id=ctx.company_id,
            )
            if not record:
                continue
            for key, value in record.entity_memory.items():
                blob = f"{key} {value}"
                overlap = len(q_tokens & _tokens(blob)) if q_tokens else 0
                substring = 1 if q_lower in blob.lower() else 0
                score = overlap + substring
                if score:
                    matches.append(
                        (float(score), {"key": key, "value": value, "store": name})
                    )
        matches.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in matches[:k]]

    async def write(
        self, ctx: RunContext, key: str, value: str, store: str = "default"
    ) -> None:
        if not ctx.user_id:
            return
        await self._store.merge_entities(
            ctx.tenant_id,
            ctx.user_id,
            self._namespace(store),
            {key: value},
            max_entities=self._config.max_entities,
            company_id=ctx.company_id,
        )

    async def remove(
        self, ctx: RunContext, key: str, store: str = "default"
    ) -> None:
        if not ctx.user_id:
            return
        record = await self._store.load(
            ctx.tenant_id,
            ctx.user_id,
            self._namespace(store),
            company_id=ctx.company_id,
        )
        if not record or key not in record.entity_memory:
            return
        del record.entity_memory[key]
        record.touch()
        await self._store.save(record, company_id=ctx.company_id)

    async def list_stores(self, ctx: RunContext) -> list[str]:
        del ctx
        return self._store_names()

    async def curate(
        self, ctx: RunContext, turn_summary: str
    ) -> dict[str, str]:
        if not turn_summary.strip() or not ctx.user_id:
            return {}
        facts = {"last_turn": turn_summary[:500]}
        store = "pending" if self._config.require_approval else "default"
        if self._config.stores and store != "pending":
            store = self._config.stores[0].name
        await self.write(ctx, "last_turn", facts["last_turn"], store=store)
        return facts
