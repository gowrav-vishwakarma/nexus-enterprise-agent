"""Built-in memory tool plugin — write / search / list durable facts."""

from __future__ import annotations

import json
from typing import Optional

from nexus.config.memory import MemoryConfig
from nexus.memory.cross_session_store import (
    CrossSessionMemoryStore,
    resolve_cross_session_namespace,
)
from nexus.memory.provider import MemoryProvider
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin


PENDING_STORE = "pending"


@tool_plugin(name="memory")
class MemoryPlugin:
    """Expose cross-session memory as agent tools.

    When a ``MemoryProvider`` is set, tools dispatch to it. Otherwise they use
    ``CrossSessionMemoryStore`` (``load`` / ``save`` / ``merge_entities``) so
    existing stores such as ``TenantMemoryStore`` need no changes.
    """

    def __init__(
        self,
        store: Optional[CrossSessionMemoryStore] = None,
        config: Optional[MemoryConfig] = None,
        agent_name: str = "",
        provider: Optional[MemoryProvider] = None,
    ):
        self._store = store
        self._config = config or MemoryConfig()
        self._agent_name = agent_name
        self._provider = provider

    def _namespace(self, store_name: str = "") -> str:
        base = resolve_cross_session_namespace(self._config.namespace, self._agent_name)
        if store_name and store_name != "default":
            return f"{base}:{store_name}"
        return base

    def _store_names(self) -> list[str]:
        if self._config.stores:
            return [s.name for s in self._config.stores]
        return ["default"]

    def _write_store(self, store: str) -> str:
        if self._config.require_approval and store != PENDING_STORE:
            return PENDING_STORE
        return store

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
        target = self._write_store(store)
        if self._provider is not None:
            await self._provider.write(ctx, key, value, store=target)
            return json.dumps({"ok": True, "store": target, "key": key})
        if self._store is None:
            return json.dumps({"ok": False, "error": "memory store not configured"})
        ns = self._namespace(target)
        await self._store.merge_entities(
            ctx.tenant_id,
            ctx.user_id,
            ns,
            {key: value},
            max_entities=self._config.max_entities,
            company_id=ctx.company_id,
        )
        return json.dumps({"ok": True, "store": target, "key": key})

    @tool(name="remove", description="Remove a memory fact by key.")
    async def remove(
        self,
        key: str,
        store: str = "default",
        ctx: Optional[RunContext] = None,
    ) -> str:
        if ctx is None or not ctx.user_id or not ctx.should_persist:
            return json.dumps({"ok": False, "error": "memory remove skipped"})
        if self._provider is not None:
            await self._provider.remove(ctx, key, store=store)
            return json.dumps({"ok": True, "store": store, "key": key})
        if self._store is None:
            return json.dumps({"ok": False, "error": "memory store not configured"})
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
        if self._provider is not None:
            hits = await self._provider.search(ctx, query="", k=self._config.max_entities)
            entries = {
                str(h.get("key")): str(h.get("value"))
                for h in hits
                if h.get("store", store) in (store, "default") or store == "default"
            }
            return json.dumps({"ok": True, "store": store, "entries": entries})
        if self._store is None:
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
        if self._provider is not None:
            matches = await self._provider.search(ctx, query, k=k)
            if store != "default":
                matches = [m for m in matches if m.get("store", store) == store]
            return json.dumps({"ok": True, "store": store, "matches": matches})
        if self._store is None:
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


class HITLMemoryPlugin(MemoryPlugin):
    """Memory plugin plus approve / reject / edit when ``require_approval`` is on."""

    @tool(name="approve", description="Approve a pending memory fact so it can be injected.")
    async def approve(
        self,
        key: str,
        store: str = "default",
        ctx: Optional[RunContext] = None,
    ) -> str:
        pending = await self._load_entries(PENDING_STORE, ctx)
        if key not in pending:
            return json.dumps({"ok": False, "error": "pending key not found"})
        value = pending[key]
        if self._provider is not None and ctx is not None:
            await self._provider.write(ctx, key, value, store=store)
            await self._provider.remove(ctx, key, store=PENDING_STORE)
        else:
            await self._write_kv(store, key, value, ctx)
            await self._delete_kv(PENDING_STORE, key, ctx)
        return json.dumps({"ok": True, "store": store, "key": key})

    @tool(name="reject", description="Discard a pending memory fact.")
    async def reject(
        self,
        key: str,
        ctx: Optional[RunContext] = None,
    ) -> str:
        pending = await self._load_entries(PENDING_STORE, ctx)
        if key not in pending:
            return json.dumps({"ok": False, "error": "pending key not found"})
        if self._provider is not None and ctx is not None:
            await self._provider.remove(ctx, key, store=PENDING_STORE)
        else:
            await self._delete_kv(PENDING_STORE, key, ctx)
        return json.dumps({"ok": True, "key": key})

    @tool(name="edit", description="Edit a pending memory fact before approving it.")
    async def edit(
        self,
        key: str,
        value: str,
        ctx: Optional[RunContext] = None,
    ) -> str:
        pending = await self._load_entries(PENDING_STORE, ctx)
        if key not in pending:
            return json.dumps({"ok": False, "error": "pending key not found"})
        if self._provider is not None and ctx is not None:
            await self._provider.write(ctx, key, value, store=PENDING_STORE)
        else:
            await self._write_kv(PENDING_STORE, key, value, ctx)
        return json.dumps({"ok": True, "store": PENDING_STORE, "key": key})

    async def _load_entries(
        self, store: str, ctx: Optional[RunContext]
    ) -> dict[str, str]:
        if ctx is None or not ctx.user_id:
            return {}
        if self._provider is not None:
            hits = await self._provider.search(ctx, query="", k=self._config.max_entities)
            return {
                str(h.get("key")): str(h.get("value"))
                for h in hits
                if h.get("store") == store
            }
        if self._store is None:
            return {}
        record = await self._store.load(
            ctx.tenant_id,
            ctx.user_id,
            self._namespace(store),
            company_id=ctx.company_id,
        )
        return dict(record.entity_memory) if record else {}

    async def _write_kv(
        self, store: str, key: str, value: str, ctx: Optional[RunContext]
    ) -> None:
        if ctx is None or self._store is None or not ctx.user_id:
            return
        await self._store.merge_entities(
            ctx.tenant_id,
            ctx.user_id,
            self._namespace(store),
            {key: value},
            max_entities=self._config.max_entities,
            company_id=ctx.company_id,
        )

    async def _delete_kv(
        self, store: str, key: str, ctx: Optional[RunContext]
    ) -> None:
        if ctx is None or self._store is None or not ctx.user_id:
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


def create_memory_plugin(
    store: Optional[CrossSessionMemoryStore],
    config: MemoryConfig,
    agent_name: str = "",
    provider: Optional[MemoryProvider] = None,
) -> MemoryPlugin:
    """Factory used by AgentRunner."""
    cls: type[MemoryPlugin] = HITLMemoryPlugin if config.require_approval else MemoryPlugin
    return cls(store, config, agent_name=agent_name, provider=provider)
