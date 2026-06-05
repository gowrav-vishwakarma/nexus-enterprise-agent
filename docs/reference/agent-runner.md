# Runner and orchestration runtime

**Who this is for:** Developers calling `run()` or `run_stream()` who need every constructor and method parameter.

## Key terms

- **AgentRunner** — Runs one agent's loop.
- **AgentOrchestrator** — Runs a multi-agent team.
- **OrchestrationRuntime** — Loads a YAML manifest and creates the right executor (runner or orchestrator).
- **Blocking** — `run()` waits and returns a full result object.
- **Streaming** — `run_stream()` yields events as the LLM generates text.

## AgentRunner constructor

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `config` | Yes | — | `AgentConfig` for this agent |
| `tool_registry` | Yes | — | Registered tools the LLM can call |
| `storage_config` | No | in-memory | `SessionStorageConfig` or `SessionManager` |
| `run_context` | No | empty `RunContext()` | Customer, user, chat id for this call |
| `event_emitter` | No | new `NexusEventEmitter` | Observability event hook |
| `cross_session_memory_store` | No | `None` | Store for facts across chat threads |

Storage resolution order: `storage_config` on runner → `config.storage` → in-memory.

## AgentRunner.run()

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `user_message` | Yes | — | The user's input text |
| `session_id` | No | from `RunContext` or new UUID | Override chat thread id for this call |
| `initial_context` | No | `None` | Key/value merged into session metadata once |
| `stream` | No | `config.stream_output` | If `True`, raises — use `run_stream()` instead |

Returns `AgentRunResult` with `final_response`, `turns_used`, `status`, etc.

## AgentRunner.run_stream()

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `user_message` | Yes | — | The user's input text |
| `session_id` | No | from `RunContext` or new UUID | Override chat thread id |
| `stream` | No | `config.stream_output` | Should be `True` for streaming |

Returns `AsyncIterator[AgentStreamEvent]`. Event types include `content`, `final_response`, `tool_call`, etc.

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

- [Run context](run-context.md)
- [Streaming](streaming.md)
- [Multi-agent](multi-agent.md)
