# Custom memory stores

**Who this is for:** Developers whose product already has a user-memory table (or needs company-scoped facts) and want Nexus to load/save that layout.

## Key terms

- **Cross-session memory store** — Implements `CrossSessionMemoryStore` (`load` / `save` / `merge_entities`).
- **Named store** — A bucket inside memory (for example `user` vs `memory`) selected via `MemoryConfig.stores`.
- **Namespace** — Isolation key: base namespace (agent name or `memory.namespace`), plus `:{store_name}` for named stores.
- **Memory plugin** — Built-in tools `memory.write` / `search` / `list` / `remove` registered when `memory.expose_tools` is true.

## When to implement a custom store

| Situation | Use |
|-----------|-----|
| Built-in SQLite / Postgres / Redis is fine | Pass `cross_session_memory_store=` or let `PersistenceFactory` pick from `adapter` |
| Your table has different columns / company scope / char caps | Custom class implementing `CrossSessionMemoryStore` |

Keep the runner on flat `entity_memory` dicts. Adapt at the store boundary only.

## CrossSessionMemoryStore — required methods

Implement these three methods (all `async`). Optional `company_id` is passed from `RunContext.company_id` by the runner, curator, and memory plugin. Built-in stores ignore it; product stores may require it.

| Method | Required? | What it does |
|--------|-----------|--------------|
| `load(tenant_id, user_id, namespace, *, company_id=None)` | Yes | Return one `CrossSessionMemoryRecord`, or `None` |
| `save(record, *, company_id=None)` | Yes | Upsert the full record (replace `entity_memory`) |
| `merge_entities(tenant_id, user_id, namespace, entities, *, max_entities, company_id=None)` | Yes | Merge key/value facts; enforce `max_entities` |

```python
from typing import Optional
from nexus.memory.cross_session_store import (
    CrossSessionMemoryRecord,
    CrossSessionMemoryStore,
)

class MyProductMemoryStore:
    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]:
        ...

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None:
        ...

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
        company_id: Optional[str] = None,
    ) -> CrossSessionMemoryRecord:
        ...
```

`CrossSessionMemoryRecord` fields: `tenant_id`, `user_id`, `namespace`, `entity_memory` (dict of string key → string value), `updated_at`.

## Optional: `search` hook

The memory plugin’s `memory.search` tool looks for an optional method on your store:

```python
async def search(
    self,
    tenant_id: Optional[str],
    user_id: str,
    namespace: str,
    query: str,
    *,
    k: int = 5,
    company_id: Optional[str] = None,
) -> list[dict]:
    """Return matches such as [{"key": "...", "value": "..."}, ...]."""
    ...
```

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `search(...)` | No | — | If missing, the plugin loads the record and does a simple substring filter |

Accepting `company_id=` keeps the signature aligned with `load`. Older stores without that kwarg still work: the plugin falls back if calling with `company_id` raises `TypeError`.

## Wire it

**Directly on the runner (preferred for SaaS apps):**

```python
runner = AgentRunner(
    config=agent_config,  # include MemoryConfig(enabled=True, ...)
    cross_session_memory_store=MyProductMemoryStore(dsn=...),
    run_context=ctx,
)
```

**Via PersistenceFactory:**

```python
from nexus.config.storage import SessionStorageConfig
from nexus.persistence.factory import PersistenceFactory

bundle = PersistenceFactory.from_storage_config(
    SessionStorageConfig(
        adapter="memory",  # session backend; independent of memory store
        custom_memory_adapter_class="myapp.memory.MyProductMemoryStore",
        adapter_config={"dsn": "..."},
    )
)
```

`adapter_config` is passed as kwargs to your store constructor.

When `memory.expose_tools` is `True`, the runner registers the memory plugin and tool calls hit `merge_entities` / `load` / `save` / optional `search` on this store.

## Named stores and inject

When `MemoryConfig.stores` lists buckets with `inject="always"`, the runner loads **each** of those namespaces and merges them for the system prompt. Keys from multiple stores are prefixed as `{store}/{key}`. Soft `char_budget` trims inject only (it does not delete rows).

Namespace rule (same as the memory plugin):

- Base = `memory.namespace` or the agent name
- Named store `user` → `{base}:user`
- Store name `default` (or empty stores list) → base only

See [Memory](../reference/memory.md).

## Next steps

- [Memory](../reference/memory.md)
- [Custom storage adapters](custom-storage-adapter.md) (chat sessions)
- [Persistence resolver](persistence-resolver.md)
