# Run context

**Who this is for:** Developers wiring multi-tenant apps or tools that need request-scoped data.

## Key terms

- **Tenant** — One customer or organization in a multi-tenant app.
- **Company** — A company inside a tenant (multi-company products).
- **User** — One person using your app.
- **Session** — One chat thread (conversation). Same as **chat thread id**.
- **Metadata** — Extra key/value data your tools can read.
- **Service registry** — Private handles (DB pools, HTTP clients) on `RunContext` that are never serialized.
- **SessionScope** — The tenant / company / user filter used by storage and stores. Built with `to_scope()`.

## RunContext fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `tenant_id` | No | `None` | Which customer/org owns this call |
| `company_id` | No | `None` | Which company within the tenant (multi-company products) |
| `user_id` | No | `None` | Which person (needed for cross-chat memory) |
| `user_name` | No | `None` | Display name (copied onto the saved session when present) |
| `session_id` | No | `None` | Default chat thread id if `run()` omits `session_id` |
| `request_id` | No | `None` | Your tracing or correlation id |
| `channel` | No | `"web"` | Where the request came from (`web`, `voice`, `cron`, …) |
| `branch_id` | No | `None` | Optional branch / environment id for your app |
| `auth` | No | `{}` | Auth claims your tools can read (never sent to the LLM) |
| `is_cron` | No | `False` | Marks a scheduled job; turns off persistence via `should_persist` |
| `is_subagent` | No | `False` | Marks a nested agent run; turns off persistence via `should_persist` |
| `persistable` | No | `True` | Explicit off-switch for saving chat history and durable side effects |
| `metadata` | No | `{}` | Arbitrary bag; tools read via `ctx.get("key")` |

Both `AgentRunner` and `AgentOrchestrator` default to an empty `RunContext()` if you omit it.

### Persistence helper

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `should_persist` | — (property) | derived | `False` when `persistable` is `False`, or when `is_cron` / `is_subagent` is `True`; otherwise `True` |

The runner skips session save/append when `should_persist` is `False`. Memory and skill_manage write tools also skip durable writes in that case.

## Service registry methods

Services (database pools, HTTP clients, feature flags) live in a private dict. They are **not** part of `metadata` and are never serialized with the session.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `service(key, default=None)` | No | — | Look up one registered service |
| `with_service(key, value)` | No | — | Register one service; returns `self` for chaining |
| `bind_services(**services)` | No | — | Register many services at once; returns `self` |
| `to_scope()` | No | — | Build a `SessionScope` from `tenant_id` / `company_id` / `user_id` |

```python
from nexus import RunContext

ctx = (
    RunContext(tenant_id="acme", company_id="co-1", user_id="u-42")
    .with_service("db", db_pool)
    .bind_services(http=http_client, flags=feature_flags)
)

pool = ctx.service("db")
scope = ctx.to_scope()  # SessionScope for storage load/list/delete
```

## When you need it

Use an explicit `RunContext` when you have:

- Multiple customers (tenants) or companies
- Per-user chat history
- Cross-chat memory (needs `user_id`)
- Tools that need request data (plan tier, database handle, etc.)
- Cron or subagent runs that must not write chat history (`is_cron` / `is_subagent`)

For a local script with one user, you can skip it and pass `session_id=` only on `run()`.

## Tool injection

If a tool declares a `RunContext` parameter, the registry injects it automatically:

```python
@tool(name="tenant_settings")
def tenant_settings(ctx: RunContext) -> str:
    return f"Settings for tenant {ctx.tenant_id} company {ctx.company_id}"
```

Tools can also **write** metadata for later tools in the same run:

```python
@tool(name="reserve_slot")
def reserve_slot(ctx: RunContext, slot_id: str) -> str:
    ctx.set("reserved_slot", slot_id)
    return f"Reserved {slot_id}"
```

See [runtime-control.md](../guides/runtime-control.md) for supervision and branching patterns.

## Multi-agent teams

Pass one `RunContext` into `AgentOrchestrator` or `OrchestrationRuntime`. Member runners get derived chat ids: `{group_session_id}_{member_name}`.

Set `session_id` **before** creating the orchestrator/runtime.

## Per-request skills

Pass skill names in metadata (with `activation_mode` `explicit` or `both`):

```python
RunContext(metadata={"skills": ["code-review"]})
```

See [skills.md](skills.md).

## Voice agents

The cascaded voice pipeline writes language and IVR keys into `metadata` before each LLM turn. Tools read and write the same bag on `RunContext`:

| Key | Written by | Read in tools |
|-----|------------|---------------|
| `reply_language`, `reply_language_name`, `detected_language`, `allowed_languages` | Pipeline (hi, en, gu, ta, te, bn, mr, …) | Optional in custom tools |
| `ivr_actions` | `ivr_menu` tools | Transport / telephony layer |
| `dtmf_buffer` | WebSocket/SIP transport | `collect_dtmf` |
| `dtmf_expected`, `ivr_terminal` | `ivr_menu` tools | Pipeline turn control |

Full table and Jinja examples: [realtime-agents.md](realtime-agents.md#voice-metadata-prompts-and-tools).

## Next steps

- [Runtime control](../guides/runtime-control.md)
- [Architecture](../architecture.md)
- [Storage](storage.md)
- [Custom storage adapter](../guides/custom-storage-adapter.md)
