# Runner and orchestration runtime

**Who this is for:** Developers calling `run()` or `run_stream()` who need every constructor and method parameter.

## Key terms

- **AgentRunner** — Runs one agent's loop.
- **AgentOrchestrator** — Runs a multi-agent team.
- **OrchestrationRuntime** — Loads a YAML manifest and creates the right executor (runner or orchestrator).
- **Blocking** — `run()` waits and returns a full result object.
- **Streaming** — `run_stream()` yields events as the LLM generates text.
- **SessionScope** — Tenant / company / user filter for storage load/save (from `RunContext.to_scope()`).
- **Resume** — Continue a paused run after client tools or elicitations return.

## AgentRunner constructor

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `config` | Yes | — | `AgentConfig` for this agent |
| `tool_registry` | Yes | — | Registered tools the LLM can call |
| `storage_config` | No | in-memory | `SessionStorageConfig` or `SessionManager` |
| `run_context` | No | empty `RunContext()` | Customer, user, chat id for this call |
| `event_emitter` | No | new `NexusEventEmitter` | Observability event hook |
| `cross_session_memory_store` | No | `None` | Store for facts across chat threads |
| `on_turn_end` | No | `None` | Async hook after each persisted turn; may return `TurnDecision` to stop or inject a message |

Storage resolution order: `storage_config` on runner → `config.storage` → in-memory.

## SessionScope wiring

Every load / append / save passes a scope built from the current `RunContext` (`tenant_id`, `company_id`, `user_id`). You do not pass scope into `run()` yourself — set identity on `RunContext` before constructing or updating the runner.

```python
ctx = RunContext(tenant_id="acme", company_id="co-1", user_id="u-42")
runner = AgentRunner(config, registry, run_context=ctx, storage_config=storage)
# Internally: scope = ctx.to_scope() on load_session / append_turn / save
```

See [storage.md](storage.md) and [run-context.md](run-context.md).

## Persistable / should_persist

| Source | Effect |
|--------|--------|
| `RunContext.persistable=False` | No session save or append |
| `RunContext.is_cron=True` | Same (via `should_persist`) |
| `RunContext.is_subagent=True` | Same |
| `should_persist` is `True` | Normal persistence |

When `should_persist` is `False`, the loop still runs in memory for that request, but durable session writes are skipped. Memory and skill_manage write tools also no-op.

## AgentRunner.run()

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `user_message` | Yes | — | The user's input text |
| `session_id` | No | from `RunContext` or new UUID | Override chat thread id for this call |
| `initial_context` | No | `None` | Key/value merged into session metadata and checkpoint `state` once at run start |
| `stream` | No | `config.stream_output` | If `True`, raises — use `run_stream()` instead |

Returns `AgentRunResult` with `final_response`, `turns_used`, `status`, `state`, `pending_interactions` (when `status="paused"`), etc.

The agent's tool allow-list comes from `AgentConfig.toolset` (resolved against the runner's tool registry), or from a per-run `run_context["toolset_override"]`. When `toolset` is `None`, every registered tool is visible and the legacy `tool_plugins` namespace filter still applies. Do not combine a non-empty `tool_plugins` with a toolset that contains flat (non-namespaced) tools, or the plugin filter may drop the flat tools. See [tools.md](tools.md).

## AgentRunner.run_stream()

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `user_message` | Yes | — | The user's input text |
| `session_id` | No | from `RunContext` or new UUID | Override chat thread id |
| `initial_context` | No | `None` | Same as `run()` — seeds metadata and checkpoint state |
| `stream` | No | `config.stream_output` | Should be `True` for streaming |

Returns `AsyncIterator[AgentStreamEvent]`. Event types include `content`, `tool_call`, `client_tool_call`, `elicitation`, `paused`, `final_response`, etc. See [streaming.md](streaming.md).

## Turn-end hook (`on_turn_end`)

Optional async callback on `AgentRunner(on_turn_end=...)`. After each completed turn (and state sync), Nexus calls your hook with a `TurnContext`. Return `None` or `TurnDecision(action="continue")` for default behaviour, `TurnDecision(action="stop")` to end the run with `status="interrupted"`, or `TurnDecision(action="inject", message="...")` to start the next loop iteration with that user message. Hook errors are logged and treated as continue. This is the deterministic alternative to LangGraph conditional edges — see [porting-from-langgraph.md](../guides/porting-from-langgraph.md).

## AgentRunner.resume()

Continue after a client tool or elicitation paused the loop:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `session_id` | Yes | — | Chat thread that has `pending_interactions` |
| `results` | Yes | — | List of `{"tc_id"\|"call_id": ..., "content": "..."}` |
| `stream` | No | `False` | When `True`, continues via an internal streaming loop and returns the final `AgentRunResult` |

```python
result = await runner.resume(
    "chat-1",
    results=[{"tc_id": "TC1", "content": "picked report.pdf"}],
)
```

Raises if the session is missing or has no pending interactions. Full flow: [runtime-control.md](../guides/runtime-control.md#pause-and-resume-client-tools).

## Runtime tool granting

Adjust a live agent's tool allow-list between turns (schemas are re-filtered each turn):

| Method | What it does |
|--------|--------------|
| `grant_tools(names)` | Add explicit tool name(s) to the allow-list |
| `grant_toolset(name_or_names)` | Resolve a defined toolset and union it in |
| `revoke_tools(names)` | Remove tool name(s) from the allow-list |

These are no-ops when the agent has no toolset restriction (`config.toolset=None`), because every registered tool is already visible. See [tools.md](tools.md#runtime-tool-granting).

## AgentOrchestrator

Same constructor args as `AgentRunner`, but `config` is `AgentGroupConfig`.

Same `run()` / `run_stream()` signatures. Returns `AgentGroupResult`.

**Team caveat:** Set `RunContext.session_id` before creating the orchestrator. Member chat ids are fixed at init.

## OrchestrationRuntime.from_manifest()

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `manifest` | Yes | — | Loaded `OrchestrationManifest` |
| `run_context` | Yes | — | Who is calling and which chat thread |
| `tool_registry` | No | `None` | Pre-built registry; YAML plugins still load |
| `persistence_resolver` | No | `None` | Per-tenant storage override |
| `event_emitter` | No | `None` | Observability (single-agent root only) |
| `cross_session_enabled` | No | `True` | Build cross-chat memory store from manifest storage |

Methods: `run(user_message)`, `run_stream(user_message, stream=None)`.

Annotated examples:

- [../assets/complete-run.annotated.py](../assets/complete-run.annotated.py)
- [../assets/complete-agent.annotated.py](../assets/complete-agent.annotated.py)

## Chat thread id priority

1. `run(session_id=...)`
2. `RunContext.session_id`
3. Auto-generated UUID

The runner syncs the resolved id back onto `RunContext`.

## Next steps

- [Pipelines guide](../guides/pipelines.md)
- [Runtime control](../guides/runtime-control.md)
- [Run context](run-context.md)
- [Tools](tools.md) — toolsets and client tools
- [Streaming](streaming.md)
- [Events](events.md)
- [Multi-agent](multi-agent.md)
