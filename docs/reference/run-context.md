# Run context

**Who this is for:** Developers wiring multi-tenant apps or tools that need request-scoped data.

## Key terms

- **Tenant** — One customer or organization in a multi-tenant app.
- **User** — One person using your app.
- **Session** — One chat thread (conversation). Same as **chat thread id**.
- **Metadata** — Extra key/value data your tools can read.

## RunContext fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `tenant_id` | No | `None` | Which customer/org owns this call |
| `user_id` | No | `None` | Which person (needed for cross-chat memory) |
| `session_id` | No | `None` | Default chat thread id if `run()` omits `session_id` |
| `request_id` | No | `None` | Your tracing or correlation id |
| `metadata` | No | `{}` | Arbitrary bag; tools read via `ctx.get("key")` |

Both `AgentRunner` and `AgentOrchestrator` default to an empty `RunContext()` if you omit it.

## When you need it

Use an explicit `RunContext` when you have:

- Multiple customers (tenants)
- Per-user chat history
- Cross-chat memory (needs `user_id`)
- Tools that need request data (plan tier, database handle, etc.)

For a local script with one user, you can skip it and pass `session_id=` only on `run()`.

## Tool injection

If a tool declares a `RunContext` parameter, the registry injects it automatically:

```python
@tool(name="tenant_settings")
def tenant_settings(ctx: RunContext) -> str:
    return f"Settings for tenant {ctx.tenant_id}"
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

## Next steps

- [Runtime control](../guides/runtime-control.md)
- [Architecture](../architecture.md)
- [Storage](storage.md)
