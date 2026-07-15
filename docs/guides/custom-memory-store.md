# Custom memory stores

**Who this is for:** Developers whose product already has a user-memory table (or needs company-scoped facts) and want Nexus to load/save that layout.

## Key terms

- **Cross-session memory store** — Implements `CrossSessionMemoryStore` (`load` / `save` / `merge_entities`).
- **Named store** — A bucket inside memory (for example `user` vs `memory`) selected via `MemoryConfig.stores`.
- **Namespace** — Isolation key: base namespace (agent name or `memory.namespace`), plus `:{store_name}` for named stores.

## When to implement a custom store

| Situation | Use |
|-----------|-----|
| Built-in SQLite / Postgres / Redis is fine | Pass `cross_session_memory_store=` or let `PersistenceFactory` pick from `adapter` |
| Your table has different columns / company scope / char caps | Custom class implementing `CrossSessionMemoryStore` |

Keep the runner on flat `entity_memory` dicts. Adapt at the store boundary only.

## Protocol sketch

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

`company_id` is optional. Built-in stores ignore it; product stores (for example AiTalk) can require it.

## Wire it

**Directly on the runner (preferred for SaaS apps):**

```python
runner = AgentRunner(
    config=agent_config,
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

## Named stores and inject

When `MemoryConfig.stores` lists buckets with `inject="always"`, the runner loads **each** of those namespaces and merges them for the system prompt. Keys from multiple stores are prefixed as `{store}/{key}`. Soft `char_budget` trims inject only (it does not delete rows).

See [Memory](../reference/memory.md).

## Next steps

- [Memory](../reference/memory.md)
- [Custom storage adapters](custom-storage-adapter.md) (chat sessions)
- [Persistence resolver](persistence-resolver.md)
