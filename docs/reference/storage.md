# Storage

**Who this is for:** Developers choosing where chat history is saved.

## Key terms

- **Adapter** — The backend type: memory, file, SQLite, PostgreSQL, or Redis.
- **Tenant-scoped** — Files organized by customer and user under a data root folder.
- **Session JSON** — The saved record for one chat thread (turns, tool calls, memory).

## Where to configure

**Preferred:** `storage_config` on `AgentRunner` or `AgentOrchestrator`.

**Fallback:** `AgentConfig.storage` (simple local scripts only).

## SessionStorageConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `adapter` | No | `"memory"` | Backend type |
| `adapter_config` | No | `{}` | Adapter-specific settings |

## Adapters

| Adapter | What it does |
|---------|--------------|
| `memory` | In-process only; lost when process exits |
| `file` | One `session.json` per chat under tenant/user folders |
| `sqlite` | One database file per user with one row per chat |
| `postgresql` | Your database; JSON blob per session row |
| `redis` | Your Redis; JSON keys with index per tenant/user |

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

- `turns[]` — user message, LLM messages, token counts
- `tool_calls[]` — tool name, input, raw and summarized responses
- `summary_text` — rolling narrative from folded turns (when `context_summary` is enabled)
- `summary_through_turn` — last turn index included in `summary_text`
- `tenant_id`, `user_id`, timestamps, `metadata`

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

- [Architecture](../architecture.md)
- [Persistence resolver](../guides/persistence-resolver.md)
