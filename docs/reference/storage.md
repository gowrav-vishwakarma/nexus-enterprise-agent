# Storage

**Who this is for:** Developers choosing where chat history is saved.

## Key terms

- **Adapter** — The backend type: memory, file, SQLite, PostgreSQL, Redis, or custom.
- **SessionScope** — Tenant / company / user filter for load, list, delete, and append.
- **Codec** — Converts an `AgentSession` to/from the JSON shape stored on disk or in a database.
- **Tenant-scoped** — Files organized by customer and user under a data root folder.
- **Session JSON** — The saved record for one chat thread (turns, tool calls, checkpoint `state`, metadata).

## Where to configure

**Preferred:** `storage_config` on `AgentRunner` or `AgentOrchestrator`.

**Fallback:** `AgentConfig.storage` (simple local scripts only).

## SessionStorageConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `adapter` | No | `"memory"` | Backend type (`memory`, `file`, `sqlite`, `postgresql`, `redis`, `custom`) |
| `adapter_config` | No | `{}` | Adapter-specific settings |
| `custom_adapter_class` | No | `None` | Import path when `adapter="custom"` |
| `custom_memory_adapter_class` | No | `None` | Import path for a custom `CrossSessionMemoryStore` |
| `codec_class` | No | `None` | Import path for a `SessionCodec`; empty uses `DefaultSessionCodec` |

## SessionScope

A **SessionScope** is the partition key for storage operations. Build it from `RunContext.to_scope()` (or from an `AgentSession.to_scope()`).

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `tenant_id` | No | `None` | Customer / org id; `None` means do not filter on tenant |
| `company_id` | No | `None` | Company within a tenant; `None` means do not filter on company |
| `user_id` | No | `None` | End-user id; `None` means do not filter on user |

Adapters accept `scope=` on:

- `load_session`
- `list_sessions` / `list_sessions_by_prefix`
- `delete_session`
- `append_turn` / `update_tc_summary`

Empty fields mean “do not filter on this dimension”. The runner wires scope from the current `RunContext` automatically.

```python
scope = run_context.to_scope()
session = await adapter.load_session(session_id, scope=scope)
```

## StorageAdapter interface

Every chat-history backend implements `StorageAdapter` (`nexus.session.adapters.base`). Built-in adapters and `BaseSQLStorageAdapter` already do this. If you write a backend from scratch, implement all of these (`async`):

| Method | Required? | What it does |
|--------|-----------|--------------|
| `save_session(session)` | Yes | Upsert one chat thread |
| `load_session(session_id, *, scope=None)` | Yes | Load one thread (or `None`) |
| `list_sessions(*, agent_id=None, scope=None, limit=50, offset=0)` | Yes | List threads |
| `list_sessions_by_prefix(prefix, *, scope=None, exclude_session_ids=None)` | Yes | Multi-agent history by id prefix |
| `delete_session(session_id, *, scope=None)` | Yes | Delete one thread |
| `append_turn(session_id, turn, *, scope=None)` | Yes | Append a turn after each agent loop |
| `update_tc_summary(...)` | Yes | Patch a tool-call summary (RCS) |

Full signatures, BaseSQL hooks, composite primary keys, and `_execute_in_transaction`: [Custom storage adapter](../guides/custom-storage-adapter.md).

## SessionCodec

A **SessionCodec** maps between the in-memory `AgentSession` and the JSON blob you store. Use a codec when your product’s JSON shape differs from Nexus’s canonical dump, but you still want the built-in adapters.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `SessionCodec` | — | protocol | Implement `dumps(session)` → dict and `loads(data, *, ctx=None)` → `AgentSession` |
| `DefaultSessionCodec` | — | used when `codec_class` is unset | Canonical `model_dump` / `model_validate` JSON |

Set `codec_class` on `SessionStorageConfig` to an import path such as `myapp.codecs.LegacyChatCodec`.

When your **table layout** differs (column names, composite keys), write a custom adapter instead — see [Custom storage adapter](../guides/custom-storage-adapter.md).

## Adapters

| Adapter | What it does |
|---------|--------------|
| `memory` | In-process only; lost when process exits |
| `file` | One `session.json` per chat under tenant/user folders |
| `sqlite` | One database file per user with one row per chat |
| `postgresql` | Your database; JSON blob per session row |
| `redis` | Your Redis; JSON keys with index per tenant/user |
| `custom` | Your class via `custom_adapter_class` |

### Custom-schema helpers

| Class | What it does |
|-------|--------------|
| `StorageAdapter` | Full ABC: `save_session`, `load_session`, list/delete, `append_turn`, `update_tc_summary` |
| `BaseSQLStorageAdapter` | Skeleton for SQL tables whose columns differ from Nexus defaults; handles codec + row-lock mutate for `append_turn`. Override `save_session` when the primary key is composite |
| `AiTalkChatsMemoryAdapter` | In-memory example of an AITalk-shaped table (`chatJson`, `companyId`, …) for tests and demos |

Full walkthrough: [Custom storage adapter](../guides/custom-storage-adapter.md).

Cross-session **user memory** (facts across chats) uses a different protocol — see [Custom memory stores](../guides/custom-memory-store.md) and [Memory](memory.md).
## Tenant-scoped layout

Default data root: `./tenants` (override with `NEXUS_DATA_ROOT`):

```text
{NEXUS_DATA_ROOT}/
  _index/sessions.json
  {tenant_id}/users/{user_id}/
    sessions.db
    memory.db
    {session_id}/session.json
```

Missing `tenant_id` or `user_id` map to `_default`.

Set `tenant_scoped: false` on adapter config for legacy flat paths.

## What is saved in each session

| Field | What it stores |
|-------|----------------|
| `turns[]` | User message, LLM messages, token counts |
| `tool_calls[]` | Tool name, input, raw and summarized responses, provider `call_id` |
| `summary_text` | Rolling narrative from folded turns (when `context_summary` is enabled) |
| `summary_through_turn` | Last turn index included in `summary_text` |
| `tenant_id`, `company_id`, `user_id`, `user_name` | Identity copied from `RunContext` |
| `title`, `pinned` | Sidebar title and pin flag |
| `attachment_ids` | Session-scoped staged attachment ids |
| `pending_interactions` | Client tools / elicitations waiting for `resume()` |
| `state` | Durable app checkpoint (survives the next request on the same chat thread) |
| timestamps, `metadata` | Created/updated times and arbitrary bag |

### ToolCallRecord extras

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `call_id` | No | `""` | Provider tool-call id; links the assistant tool_call message to the tool result |

## Multi-agent chat history

Each team member gets its own session JSON, not one merged file:

```text
group-sess-1_researcher  →  own session
group-sess-1_analyst     →  own session
```

Load joined history for a UI with `SessionManager.load_session_group()`.

Use **one** `storage_config` for the whole team.

## Production PostgreSQL / Redis

Install extras:

```bash
uv pip install "nexus-enterprise-agent[postgres,redis]"
```

You control DSN, schema, and table names. See [persistence-resolver guide](../guides/persistence-resolver.md).

## Environment variables

See [environment.md](environment.md) for `NEXUS_DATA_ROOT`, `NEXUS_PG_*`, `NEXUS_REDIS_*`.

## Next steps

- [Custom storage adapter](../guides/custom-storage-adapter.md)
- [Architecture](../architecture.md)
- [Persistence resolver](../guides/persistence-resolver.md)
- [Run context](run-context.md)
