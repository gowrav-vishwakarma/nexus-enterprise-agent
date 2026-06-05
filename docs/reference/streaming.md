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

| Method | Returns when not streaming | Returns when streaming |
|--------|---------------------------|------------------------|
| `run()` | `AgentRunResult` | Raises error — use `run_stream()` |
| `run_stream()` | Use `run()` instead | `AgentStreamEvent` chunks |

## Multi-agent

`AgentOrchestrator.run_stream()` and `OrchestrationRuntime.run_stream()` follow the same pattern.

The SaaS example accepts `"stream": true` on chat requests and returns SSE from `/v1/chat`. See [SaaS guide](../guides/saas-example.md).

## Next steps

- [Runner](agent-runner.md)
- [Agent config](agent-config.md)
