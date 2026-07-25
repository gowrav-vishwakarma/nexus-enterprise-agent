# Streaming

**Who this is for:** Developers building live UIs or Server-Sent Events (SSE) APIs.

## Key terms

- **Blocking** — Wait for the full reply; get one result object.
- **Streaming** — Receive chunks as the LLM generates text.
- **SSE** — Server-Sent Events; one way to push stream chunks to a web browser.
- **Paused** — The run stopped waiting for a client tool or elicitation; call `resume()`.

## Default mode

Set on `AgentConfig.stream_output` or `AgentGroupConfig.stream_output` (default: `False` = blocking).

Override per call with `stream=True` or `stream=False` on `run()` / `run_stream()`.

## Blocking

```python
result = await runner.run("Hello", stream=False)
print(result.final_response)
```

Returns `AgentRunResult`. When `status == "paused"`, inspect `result.pending_interactions` and call `resume()`.

## Streaming

```python
async for event in runner.run_stream("Hello", stream=True):
    if event.event_type == "content":
        print(event.content, end="", flush=True)
    elif event.event_type == "final_response":
        result = event.data  # full AgentRunResult
```

Returns `AsyncIterator[AgentStreamEvent]`.

`run_stream()` accepts the same `initial_context=` argument as `run()` to seed checkpoint `state` and session metadata.

### Stream event types

| `event_type` | When it fires |
|--------------|---------------|
| `content` | LLM text chunk |
| `tool_call` | Model requested a **server** tool |
| `tool_result` | Server tool finished; check `event.content` |
| `client_tool_call` | Model requested a client tool (`execution="client"`); run will pause |
| `elicitation` | Model requested user input (`*.request_user_input`); run will pause |
| `paused` | Run stopped with `pending_interactions` in `event.data` |
| `final_response` | Run done; full `AgentRunResult` in `event.data` |
| `error` | Run failed |
| `event` | Internal lifecycle signal |

### Pause / resume (summary)

```python
async for event in runner.run_stream(user_msg, stream=True):
    if event.event_type == "paused":
        pending = event.data["pending_interactions"]
        # Run client tools in your UI, then:
        result = await runner.resume(
            event.data["session_id"],
            results=[{"tc_id": p["tc_id"], "content": "..."} for p in pending],
        )
```

Full patterns: [runtime-control.md](../guides/runtime-control.md#pause-and-resume-client-tools).

### Supervision: react to tool results

Use `run_stream()` when your app must **take charge** after a tool returns — for example, escalate to a human or swap runners:

```python
escalate = False
async for event in runner.run_stream(user_msg, stream=True):
    if event.event_type == "tool_result" and "escalate" in (event.content or ""):
        escalate = True
        break
```

Structured lifecycle events: [events.md](events.md).

| Method | Returns when not streaming | Returns when streaming |
|--------|---------------------------|------------------------|
| `run()` | `AgentRunResult` | Raises error — use `run_stream()` |
| `run_stream()` | Use `run()` instead | `AgentStreamEvent` chunks |
| `resume()` | `AgentRunResult` | Pass `stream=True` only if you continue via `run` path (defaults to blocking) |

## Multi-agent

`AgentOrchestrator.run_stream()` and `OrchestrationRuntime.run_stream()` follow the same pattern.

The SaaS example accepts `"stream": true` on chat requests and returns SSE from `/v1/chat`. See [SaaS guide](../guides/saas-example.md).

## Next steps

- [Runtime control](../guides/runtime-control.md)
- [Events](events.md)
- [Runner](agent-runner.md)
- [Tools](tools.md) — `execution="client"` and toolsets
- [Agent config](agent-config.md)
