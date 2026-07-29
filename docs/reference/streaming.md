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
| `reasoning` | Reasoning ("thinking") chunk, if the model produces any |
| `tool_call` | Model requested a **server** tool |
| `tool_result` | Server tool finished; check `event.content` |
| `client_tool_call` | Model requested a client tool (`execution="client"`); run will pause |
| `elicitation` | Model requested user input (`*.request_user_input`); run will pause |
| `paused` | Run stopped with `pending_interactions` in `event.data` |
| `final_response` | Run done; full `AgentRunResult` in `event.data` |
| `error` | Run failed |
| `event` | Internal lifecycle signal |

Events are emitted **as they arrive** from the provider, in the order they occurred.
A turn that ends in a tool call still streams whatever text the model wrote first, so
you can render narration, tool calls and the final answer as one ordered timeline.

### Reasoning ("thinking")

Reasoning-capable models (Qwen3, DeepSeek-R1, Claude extended thinking, Gemini
thinking, gpt-oss) emit their private train of thought separately from the answer.
LiteLLM normalises this to `reasoning_content`, and Nexus forwards each piece as a
`reasoning` event. Reasoning never appears in `content`:

```python
async for event in runner.run_stream("Hello", stream=True):
    if event.event_type == "reasoning":
        render_thinking(event.content)   # collapse this in your UI
    elif event.event_type == "content":
        render_answer(event.content)
```

The full text is saved on the turn as `TurnRecord.reasoning`, so a stored chat can be
replayed with its thinking intact. It is deliberately **not** stored inside
`TurnRecord.llm_messages`, because those dicts are replayed verbatim into the next
provider request and an unknown key would be rejected. Nexus never sends reasoning
back to the model.

Two things to check if you see no `reasoning` events:

- **The model must be asked to think.** Use `LLMProviderConfig.enable_thinking=True`,
  or the provider's own switch (`reasoning_effort`, `thinking`) via `default_params`.
  Set `enable_thinking=False` for voice, where a leading thinking block delays the
  first spoken word. See [agent-config.md](agent-config.md#reasoning-thinking).
- **The server must parse it.** A self-hosted vLLM or SGLang deployment only fills
  `reasoning_content` when started with a matching `--reasoning-parser` (for example
  `--reasoning-parser qwen3`). Without it the model's `<think>` block stays inside
  `content` and arrives as ordinary text.

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
