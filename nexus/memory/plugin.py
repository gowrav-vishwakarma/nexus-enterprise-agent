"""Built-in memory tool plugin — write / search / list durable facts."""

from __future__ import annotations

import json
from typing import Any, Optional

from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    resolve_cross_session_namespace,
)
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="memory")
class MemoryPlugin:
    """Expose cross-session memory as agent tools."""

    def __init__(
        self,
        store: CrossSessionMemoryStore,
        config: MemoryConfig,
        agent_name: str = "",
    ):
        self._store = store
        self._config = config
        self._agent_name = agent_name

    def _namespace(self, store_name: str = "") -> str:
        base = resolve_cross_session_namespace(self._config.namespace, self._agent_name)
        if store_name and store_name != "default":
            return f"{base}:{store_name}"
        return base

    def _store_names(self) -> list[str]:
        if self._config.stores:
            return [s.name for s in self._config.stores]
        return ["default"]

    @tool(name="write", description="Save a durable fact about the user into memory.")
    async def write(
        self,
        key: str,
        value: str,
        store: str = "default",
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None or not ctx.user_id or not ctx.should_persist:
            return json.dumps({"ok": False, "error": "memory write skipped (no user / non-persistable)"})
        ns = self._namespace(store)
        await self._store.merge_entities(
            ctx.tenant_id,
            ctx.user_id,
            ns,
            {key: value},
            max_entities=self._config.max_entities,
            company_id=ctx.company_id,
        )
        return json.dumps({"ok": True, "store": store, "key": key})

    @tool(name="remove", description="Remove a memory fact by key.")
    async def remove(
        self,
        key: str,
        store: str = "default",
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None or not ctx.user_id or not ctx.should_persist:
            return json.dumps({"ok": False, "error": "memory remove skipped"})
        ns = self._namespace(store)
        record = await self._store.load(
            ctx.tenant_id, ctx.user_id, ns, company_id=ctx.company_id
        )
        if not record or key not in record.entity_memory:
            return json.dumps({"ok": False, "error": "key not found"})
        del record.entity_memory[key]
        record.touch()
        await self._store.save(record, company_id=ctx.company_id)
        return json.dumps({"ok": True, "store": store, "key": key})

    @tool(name="list", description="List memory facts in a store.")
    async def list_facts(
        self,
        store: str = "default",
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None or not ctx.user_id:
            return json.dumps({"ok": True, "entries": {}})
        ns = self._namespace(store)
        record = await self._store.load(
            ctx.tenant_id, ctx.user_id, ns, company_id=ctx.company_id
        )
        entries = dict(record.entity_memory) if record else {}
        return json.dumps({"ok": True, "store": store, "entries": entries})

    @tool(name="search", description="Search memory facts by substring query.")
    async def search(
        self,
        query: str,
        store: str = "default",
        k: int = 5,
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None or not ctx.user_id:
            return json.dumps({"ok": True, "matches": []})
        ns = self._namespace(store)
        search_fn = getattr(self._store, "search", None)
        if callable(search_fn):
            try:
                matches = await search_fn(
                    ctx.tenant_id,
                    ctx.user_id,
                    ns,
                    query,
                    k=k,
                    company_id=ctx.company_id,
                )
            except TypeError:
                matches = await search_fn(ctx.tenant_id, ctx.user_id, ns, query, k=k)
            return json.dumps({"ok": True, "store": store, "matches": matches})
        record = await self._store.load(
            ctx.tenant_id, ctx.user_id, ns, company_id=ctx.company_id
        )
        if not record:
            return json.dumps({"ok": True, "matches": []})
        q = query.lower()
        matches = [
            {"key": key, "value": value}
            for key, value in record.entity_memory.items()
            if q in key.lower() or q in value.lower()
        ][:k]
        return json.dumps({"ok": True, "store": store, "matches": matches})


def create_memory_plugin(
    store: CrossSessionMemoryStore,
    config: MemoryConfig,
    agent_name: str = "",
) -> MemoryPlugin:
    """Factory used by AgentRunner."""
    return MemoryPlugin(store, config, agent_name=agent_name)
