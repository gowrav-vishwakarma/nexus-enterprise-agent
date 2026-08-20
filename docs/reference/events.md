# Events and observability

**Who this is for:** Developers who want to react to agent lifecycle, tool calls, and voice session events — for logging, webhooks, OpenTelemetry, or supervision.

## Key terms

- **Event emitter** — `NexusEventEmitter`; fans out framework events to one or more sinks.
- **Sink** — A destination for events (stdout, callback, webhook, OpenTelemetry).
- **Supervision** — Using events or `run_stream()` to observe a run; see [runtime-control.md](../guides/runtime-control.md) for branching patterns.

## Why use events?

`run_stream()` is best for **live UIs** (token chunks, tool results). `NexusEventEmitter` is best for **structured observability** across the full lifecycle — turns, tools, memory, voice sessions — without coupling to the streaming API.

## Basic setup

```python
from nexus import AgentRunner
from nexus.events.emitter import NexusEventEmitter, CustomCallbackSink
from nexus.events.models import NexusEvent, NexusEventType

async def handle_event(event: NexusEvent) -> None:
    if event.event_type == NexusEventType.TOOL_CALL_COMPLETED:
        tool_name = event.data.get("tool_name")
        print(f"Tool finished: {tool_name}")

emitter = NexusEventEmitter()
emitter.add_sink(CustomCallbackSink(handle_event))

runner = AgentRunner(config, registry, event_emitter=emitter)
await runner.run("Hello")
```

Pass the same `event_emitter=` to `OrchestrationRuntime.from_manifest()` or to
`AgentOrchestrator`. The orchestrator fans it out to member runners and nested
groups. Attach emitters to members yourself only when you build those runners
manually, without an orchestrator.

## Built-in sinks

| Sink | What it does |
|------|--------------|
| `StdoutEventSink` | Prints JSON lines to stdout (default when `trace_enabled=True`) |
| `CustomCallbackSink` | Calls your async `callback(event)` |
| `WebhookEventSink` | POSTs JSON to a URL |
| `OTelEventSink` | Exports spans to OpenTelemetry (needs `opentelemetry-api`) |
| `RedactingEventSink` | Wraps another sink and strips PII and secrets first |
| `AuditSink` | Writes an append-only, scope-keyed audit line per tool call and approval |

```python
from nexus.events.emitter import WebhookEventSink

emitter.add_sink(WebhookEventSink("https://your-app.com/nexus-events"))
```

## Keeping customer data out of traces

Events carry whatever the model passed to a tool, so a webhook or tracing backend
outside your tenant boundary will otherwise receive customer emails, phone numbers,
and API tokens. Wrap those sinks:

```python
from nexus.events.emitter import OTelEventSink, RedactingEventSink, WebhookEventSink

emitter.register_sink(RedactingEventSink(WebhookEventSink("https://collector/events")))
emitter.register_sink(RedactingEventSink(OTelEventSink()))
```

`RedactingEventSink` rewrites every field of an event except the ones you search on
(`event_id`, `event_type`, `timestamp`, `session_id`, `agent_id`, `turn_index`).
Email addresses become `[EMAIL]`, phone numbers `[PHONE]`, and any dict key named
like a credential (`api_key`, `token`, `password`, `authorization`, `secret`, and
their variants) becomes `[REDACTED]`. Pass `sensitive_keys={...}` to replace that
key list with your own.

The same patterns back `PIIRedactionGuard`, so a value stripped from a prompt is
stripped from a trace — see [nexus/guardrails/redaction.py](../../nexus/guardrails/redaction.py).

## Audit trail

`AuditSink` records *that* a tool ran, for compliance, without archiving the data it
carried. Give it the run's `RunContext` so each line is scope-keyed:

```python
from nexus.guardrails.audit import AuditSink

emitter.register_sink(AuditSink(ctx=run_context))
```

It logs JSON lines to the `nexus.audit` logger for `tool_call.*` and
`human_in_loop.*` events, and ignores everything else. Each line carries `scope`
(the [scope key](scope.md) at user level), `tenant_id`, `company_id`, `user_id`,
`session_id`, and the redacted event. Point the `nexus.audit` logger at a file or a
log shipper to retain it. Pass `redact=False` only if the sink writes somewhere that
is already inside your compliance boundary.

## Event types

| Category | `NexusEventType` values |
|----------|-------------------------|
| Agent | `agent.started`, `agent.completed`, `agent.error` |
| Turn | `turn.started`, `turn.completed`, `turn.error` |
| Tool | `tool_call.started`, `tool_call.completed`, `tool_call.error` |
| LLM | `llm.call_started`, `llm.call_completed`, `llm.stream.chunk`, `llm.call_error` |
| RCS | `rcs.tc_summarized`, `rcs.context_built`, `rcs.compactor_triggered`, `rcs.compactor_completed`, `rcs.cross_session_tc_reference` |
| Memory | `memory.entity_extracted` |
| Context summary | `context.summarized` |
| Session | `session.created`, `session.loaded`, `session.saved` |
| Multi-agent | `agent_group.started`, `agent_group.completed`, `agent.handoff` |
| Realtime / voice | `realtime.session_started`, `realtime.transcribed`, `realtime.barge_in`, `realtime.response_completed`, `realtime.session_ended` |
| Human-in-loop | `human_in_loop.requested`, `human_in_loop.response` (emitted on pause/resume) |

Each `NexusEvent` has `event_id`, `timestamp`, `session_id`, `agent_id`, `turn_index`, and a `data` dict with event-specific fields.

### RCS fields on completion events

`agent.completed` and `turn.completed` carry RCS savings fields:

| Event | Field | Description |
|-------|-------|-------------|
| `agent.completed` | `total_tokens_saved_by_rcs` | One-time compression savings across the run |
| `agent.completed` | `cumulative_tokens_saved_by_rcs` | Recurring input-token savings across all turns |
| `turn.completed` | `tokens_saved` | One-time savings for this turn |
| `turn.completed` | `recurring_savings` | Recurring input-token savings for this turn |

## run_stream vs events

| Mechanism | Best for | Can pause the run? |
|-----------|----------|-------------------|
| `run_stream()` | Token streaming, SSE APIs, break on `tool_result` | Yes — stop the async iterator |
| `on_turn_end` on `AgentRunner` | Deterministic stop/inject after a turn | Yes — returns `TurnDecision` |
| `NexusEventEmitter` | Logging, webhooks, OTel, audit trail | No — observe only |

For supervision that **stops** the agent when a tool returns a signal, prefer `run_stream()`. See [runtime-control.md § Supervise with run_stream](../guides/runtime-control.md).

## Enable tracing on config

Set on `AgentConfig`:

```python
AgentConfig(
    name="assistant",
    llm=...,
    trace_enabled=True,
    trace_sink="stdout",  # or "otel"
)
```

This attaches a default `StdoutEventSink` when you do not pass a custom emitter.

## Next steps

- [Runtime control guide](../guides/runtime-control.md) — supervision and branching patterns
- [Streaming](streaming.md) — `run_stream()` and `AgentStreamEvent` types
- [Agent runner](agent-runner.md) — `event_emitter` constructor parameter
