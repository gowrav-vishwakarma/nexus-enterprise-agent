# Custom storage adapters

**Who this is for:** Developers whose product already has a chats table (or a non-canonical JSON shape) and need Nexus to read/write that layout.

## Key terms

- **Adapter** — Owns how rows or files are stored (connection, table name, WHERE clause).
- **Codec** — Owns how an `AgentSession` becomes a JSON dict (and back).
- **SessionScope** — Tenant / company / user filter passed into load/list/delete/append.

## When to use a codec vs a custom adapter

| Situation | Use |
|-----------|-----|
| Same table/files as a built-in adapter, but different JSON keys inside the blob | `SessionCodec` via `codec_class` |
| Different columns, composite primary key, or product table name | Custom adapter (often subclass `BaseSQLStorageAdapter`) |
| Both different columns **and** different JSON | Custom adapter **plus** a codec |

Keep the runner on `AgentSession`. Adapt at the storage boundary only.

## SessionCodec sketch

```python
from typing import Any, Union
from nexus.session.codec import SessionCodec
from nexus.session.models import AgentSession

class SlimUiCodec:
    """Store a UI-friendly subset; expand on load."""

    def dumps(self, session: AgentSession) -> dict[str, Any]:
        return {
            "id": session.session_id,
            "title": session.title,
            "turns": [t.model_dump(mode="json") for t in session.turns],
        }

    def loads(self, data: Union[str, dict[str, Any]], *, ctx=None) -> AgentSession:
        # Parse your shape, then build AgentSession(...)
        ...
```

Wire it:

```yaml
storage:
  adapter: postgresql
  codec_class: myapp.codecs.SlimUiCodec
  adapter_config:
    dsn: ${ENV:DATABASE_URL}
```

Or in Python: set `SessionStorageConfig(codec_class="myapp.codecs.SlimUiCodec", ...)`.

## BaseSQLStorageAdapter hooks

Subclass this when your SQL table is not the default Nexus sessions table. You implement mapping; the base class provides codec encode/decode and the lock → mutate → rewrite path for `append_turn` / `update_tc_summary`.

| Hook | Required? | What it does |
|------|-----------|--------------|
| `table()` | Yes | Qualified table name, e.g. `ankpal."AiTalkChats"` |
| `json_column()` | No (default `"data"`) | Column that holds the session JSON blob |
| `id_column()` | No (default `"session_id"`) | Primary session id column |
| `row_columns(session)` | Yes | Side columns to upsert (no JSON column) |
| `scope_where(scope)` | Yes | `(sql_fragment, params)` for tenant/company/user filters |
| `_fetch_one` / `_fetch_all` / `_execute` | Yes | Driver-specific query helpers |
| `_execute_in_transaction` | Yes | Run work inside a transaction (FOR UPDATE locking) |

## AiTalkChats example

`AiTalkChatsMemoryAdapter` is an in-memory stand-in for Ankpal’s `AiTalkChats` layout. It shows the mapping you would use against Postgres:

- Identity: `tenantId` + `chatId`, with `companyId` / `userId` filters
- JSON blob column: `chatJson`
- Side columns: `companyId`, `userId`, `userName`

Sketch of the mapping (real Postgres would use asyncpg in `_fetch_*`):

```python
from nexus.session.adapters.base_sql import BaseSQLStorageAdapter
from nexus.session.models import AgentSession
from nexus.session.scope import SessionScope

class AiTalkChatsAdapter(BaseSQLStorageAdapter):
    def table(self) -> str:
        return 'ankpal."AiTalkChats"'

    def json_column(self) -> str:
        return "chatJson"

    def id_column(self) -> str:
        return "chatId"

    def row_columns(self, session: AgentSession) -> dict:
        return {
            "tenantId": session.tenant_id,
            "chatId": session.session_id,
            "companyId": session.company_id,
            "userId": session.user_id,
            "userName": session.user_name,
        }

    def scope_where(self, scope: SessionScope | None):
        if scope is None:
            return "", []
        clauses, params = [], []
        if scope.tenant_id is not None:
            clauses.append('"tenantId" = %s')
            params.append(scope.tenant_id)
        if scope.company_id is not None:
            clauses.append('"companyId" = %s')
            params.append(scope.company_id)
        if scope.user_id is not None:
            clauses.append('"userId" = %s')
            params.append(scope.user_id)
        return " AND ".join(clauses), params
```

Register with `adapter: custom` and `custom_adapter_class: myapp.storage.AiTalkChatsAdapter`.

For demos and unit tests, use `nexus.session.adapters.aitalk_chats.AiTalkChatsMemoryAdapter` directly.

## Scope checklist

1. Build `RunContext` with `tenant_id` / `company_id` / `user_id`.
2. Let the runner call `to_scope()` (or pass the same scope into your adapter).
3. Filter every load/list/delete/append with that scope so tenants cannot read each other’s chats.

## Next steps

- [Storage reference](../reference/storage.md)
- [Run context](../reference/run-context.md)
- [Persistence resolver](persistence-resolver.md)
