# Custom storage adapters

**Who this is for:** Developers whose product already has a chats table (or a non-canonical JSON shape) and need Nexus to read/write that layout.

## Key terms

- **Adapter** — Owns how rows or files are stored (connection, table name, WHERE clause).
- **Codec** — Owns how an `AgentSession` becomes a JSON dict (and back).
- **SessionScope** — Tenant / company / user filter passed into load/list/delete/append.
- **StorageAdapter** — The full abstract interface every chat-history backend must implement.
- **BaseSQLStorageAdapter** — Optional SQL skeleton: you map columns; it implements most of `StorageAdapter` for you.

## When to use a codec vs a custom adapter

| Situation | Use |
|-----------|-----|
| Same table/files as a built-in adapter, but different JSON keys inside the blob | `SessionCodec` via `codec_class` |
| Different columns, composite primary key, or product table name | Custom adapter (often subclass `BaseSQLStorageAdapter`) |
| Both different columns **and** different JSON | Custom adapter **plus** a codec |

Keep the runner on `AgentSession`. Adapt at the storage boundary only.

## StorageAdapter — full interface

If you do **not** subclass `BaseSQLStorageAdapter`, implement every method on `StorageAdapter` (`nexus.session.adapters.base`). All methods are `async`. Pass `scope=` on every read/mutate so tenants cannot see each other’s chats.

| Method | Required? | What it does |
|--------|-----------|--------------|
| `save_session(session)` | Yes | Upsert the full chat thread |
| `load_session(session_id, *, scope=None)` | Yes | Load one thread; return `None` if missing or out of scope |
| `list_sessions(*, agent_id=None, scope=None, limit=50, offset=0)` | Yes | List threads (newest first is typical) |
| `list_sessions_by_prefix(session_id_prefix, *, scope=None, exclude_session_ids=None)` | Yes | Multi-agent: sessions whose id starts with the prefix; sort by `created_at` ascending |
| `delete_session(session_id, *, scope=None)` | Yes | Delete one thread |
| `append_turn(session_id, turn, *, scope=None)` | Yes | Atomically append one turn (used after each agent turn) |
| `update_tc_summary(session_id, tc_id, summarized_response, summarized_by_turn, *, scope=None)` | Yes | Patch one tool-call summary inside the JSON (RCS) |

Signatures (abbreviated):

```python
from typing import Optional
from nexus.session.adapters.base import StorageAdapter
from nexus.session.models import AgentSession, TurnRecord
from nexus.session.scope import SessionScope

class MyStorageAdapter(StorageAdapter):
    async def save_session(self, session: AgentSession) -> None: ...

    async def load_session(
        self, session_id: str, *, scope: Optional[SessionScope] = None
    ) -> Optional[AgentSession]: ...

    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        scope: Optional[SessionScope] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]: ...

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        scope: Optional[SessionScope] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]: ...

    async def delete_session(
        self, session_id: str, *, scope: Optional[SessionScope] = None
    ) -> None: ...

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None: ...

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None: ...
```

Most products subclass `BaseSQLStorageAdapter` instead and only implement the hooks below.

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

| Hook | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `table()` | Yes | — | Qualified table name, e.g. `ankpal."AiTalkChats"` |
| `json_column()` | No | `"data"` | Column that holds the session JSON blob. You may quote camelCase names (e.g. `'"chatJson"'`); the base strips quotes when reading psycopg `dict_row` results |
| `id_column()` | No | `"session_id"` | Primary session id column used in `WHERE` / `ON CONFLICT` |
| `row_columns(session)` | Yes | — | Side columns to upsert (do **not** include the JSON column) |
| `scope_where(scope)` | Yes | — | `(sql_fragment, params)` for tenant/company/user filters (no leading `WHERE` / `AND`) |
| `_fetch_one(sql, params)` | Yes | — | Run a `SELECT`; return one row `dict` or `None` |
| `_fetch_all(sql, params)` | Yes | — | Run a `SELECT`; return a list of row dicts |
| `_execute(sql, params)` | Yes | — | Run `INSERT` / `UPDATE` / `DELETE` and commit |
| `_execute_in_transaction(work)` | Yes | — | Open a transaction; `await work(tx)` where `tx` supports `fetch_one` and `execute` (used for `FOR UPDATE` on append) |
| `_json_param(session)` | No | JSON string via codec | Override for driver-native JSON (e.g. psycopg `Json(...)`) |
| `save_session(session)` | No* | Single-column `ON CONFLICT (id_column)` | **Override when the primary key is composite** (see below) |

\*Required to override for composite primary keys.

### Transaction object for `_execute_in_transaction`

`append_turn` and `update_tc_summary` call:

```python
await self._execute_in_transaction(_work)
```

Your `work` coroutine receives a thin connection wrapper. It must support:

| Method | What it does |
|--------|--------------|
| `await tx.fetch_one(sql, params)` | `SELECT ... FOR UPDATE` path — one row dict or `None` |
| `await tx.execute(sql, params)` | `UPDATE` / write inside the same transaction |

The base then locks the row, mutates the decoded session, and rewrites via `_write_locked`.

### Composite primary keys

The default `save_session` builds:

```sql
ON CONFLICT (id_column) DO UPDATE ...
```

That is wrong when the real primary key is `(tenantId, chatId)` (or similar). In that case **override `save_session` entirely** with your own `INSERT ... ON CONFLICT (col1, col2)`. Keep `append_turn` from the base if `_write_locked`’s `UPDATE ... WHERE id_column = %s` is enough for your table; if updates must also filter by tenant, override `_write_locked` / `_lock_and_load` as well.

## AiTalkChats example

`AiTalkChatsMemoryAdapter` is an in-memory stand-in for Ankpal’s `AiTalkChats` layout. It shows the mapping you would use against Postgres:

- Identity: `tenantId` + `chatId`, with `companyId` / `userId` filters
- JSON blob column: `chatJson`
- Side columns: `companyId`, `userId`, `userName`
- Composite PK → custom `save_session`

Sketch (real Postgres would implement `_fetch_*` / `_execute*` with asyncpg or psycopg):

```python
from typing import Any, Optional
from nexus.session.adapters.base_sql import BaseSQLStorageAdapter
from nexus.session.models import AgentSession
from nexus.session.scope import SessionScope

class AiTalkChatsAdapter(BaseSQLStorageAdapter):
    def table(self) -> str:
        return 'ankpal."AiTalkChats"'

    def json_column(self) -> str:
        return '"chatJson"'

    def id_column(self) -> str:
        return '"chatId"'

    def row_columns(self, session: AgentSession) -> dict:
        return {
            '"tenantId"': session.tenant_id,
            '"chatId"': session.session_id,
            '"companyId"': session.company_id,
            '"userId"': session.user_id,
            '"userName"': session.user_name,
        }

    def scope_where(self, scope: Optional[SessionScope]):
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

    async def save_session(self, session: AgentSession) -> None:
        # Composite PK (tenantId, chatId) — do not use the base ON CONFLICT (chatId).
        session.update_timestamp()
        cols = self.row_columns(session)
        cols[self.json_column()] = self._json_param(session)
        sql = f"""
            INSERT INTO {self.table()}
                ("tenantId","chatId","companyId","userId","userName","chatJson")
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT ("tenantId","chatId") DO UPDATE SET
                "companyId" = EXCLUDED."companyId",
                "userId" = EXCLUDED."userId",
                "userName" = EXCLUDED."userName",
                "chatJson" = EXCLUDED."chatJson"
        """
        await self._execute(sql, list(cols.values()))
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
- [Custom memory stores](custom-memory-store.md)
