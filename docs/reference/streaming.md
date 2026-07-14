# Streaming

**Who this is for:** Developers building live UIs or Server-Sent Events (SSE) APIs.

## Key terms

- **Blocking** — Wait for the full reply; get one result object.
- **Streaming** — Receive chunks as the LLM generates text.
- **SSE** — Server-Sent Events; one way to push stream chunks to a web browser.

## Default mode

Set on `AgentConfig.stream_output` or `AgentGroupConfig.stream_output` (default: `False` = blocking).

Override per call with `stream=True` or `stream=False` on `run()` / `run_stream()`.

## Blocking

```python
result = await runner.run("Hello", stream=False)
print(result.final_response)
```

Returns `AgentRunResult`.

## Streaming

```python
async for event in runner.run_stream("Hello", stream=True):
    if event.event_type == "content":
        print(event.content, end="", flush=True)
    elif event.event_type == "final_response":
        result = event.data  # full AgentRunResult
```

Returns `AsyncIterator[AgentStreamEvent]`.

### Stream event types

| `event_type` | When it fires |
|--------------|---------------|
| `content` | LLM text chunk |
| `tool_call` | Model requested a tool |
| `tool_result` | Tool finished; check `event.content` |
| `final_response` | Run done; full `AgentRunResult` in `event.data` |
| `error` | Run failed |
| `event` | Internal lifecycle signal |

### Supervision: react to tool results

Use `run_stream()` when your app must **take charge** after a tool returns — for example, escalate to a human or swap runners. This is the recommended pattern for deterministic branching without a state graph:

```python
escalate = False
async for event in runner.run_stream(user_msg, stream=True):
    if event.event_type == "tool_result" and "escalate" in (event.content or ""):
        escalate = True
        break
```

Full patterns: [runtime-control.md](../guides/runtime-control.md). Structured lifecycle events: [events.md](events.md).

| Method | Returns when not streaming | Returns when streaming |
|--------|---------------------------|------------------------|
| `run()` | `AgentRunResult` | Raises error — use `run_stream()` |
| `run_stream()` | Use `run()` instead | `AgentStreamEvent` chunks |

## Multi-agent

`AgentOrchestrator.run_stream()` and `OrchestrationRuntime.run_stream()` follow the same pattern.

The SaaS example accepts `"stream": true` on chat requests and returns SSE from `/v1/chat`. See [SaaS guide](../guides/saas-example.md).

## Next steps

- [Runtime control](../guides/runtime-control.md)
- [Events](events.md)
- [Runner](agent-runner.md)
- [Agent config](agent-config.md)
