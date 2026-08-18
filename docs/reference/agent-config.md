# Agent config reference

**Who this is for:** Developers building `AgentConfig` in Python or YAML who need every field and default.

## Key terms

- **Persona** — Role, goal, and backstory that shape the system prompt.
- **Turn** — One cycle of: send messages to LLM → maybe call tools → save results.
- **RCS** — Runtime Context Summarization; keeps long tool outputs from filling the context window.
- **Memory** — Durable user facts stored across chat threads (cross-session).
- **RAG** — Optional retrieval over a document collection (`AgentConfig.rag`). Unset means no retrieve tool.

## AgentConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Unique agent id (logs, saved sessions) |
| `llm` | Yes | — | LLM provider settings |
| `persona` | No | role=`Assistant`, goal=`Help the user` | System prompt framing |
| `turns` | No | see TurnConfig | Agent loop limits |
| `rcs` | No | disabled | Context summarization |
| `memory` | No | disabled | Cross-session user memory (curator + injection) |
| `context_summary` | No | disabled (`summarize_on=None`) | Rolling `summary_text` when context fill exceeds ratio |
| `storage` | No | `None` | Fallback storage when runner has none |
| `tool_plugins` | No | `[]` | Legacy allow-list of tool plugin namespaces (`[]` = all) |
| `toolset` | No | `None` | Toolset name or list of names (defined on the tool registry) — `None` = no restriction. See [tools.md](tools.md) |

The `toolset` value refers to a pack you define on the `ToolRegistry` with `add_toolset(name, [callables])` or `discover_package(...)`. Use `toolset` for modern flat-tool allow-lists; keep `tool_plugins` only when you still use class-based `@tool_plugin` namespaces.
| `skills` | No | disabled | Static + learned skills — see [skills.md](skills.md) |
| `rag` | No | `None` | Optional retrieval. `None` registers no `rag.retrieve` tool — see [rag.md](rag.md) |
| `result_type` | No | `None` | Pydantic model for structured output |
| `trace_enabled` | No | `False` | Emit observability events |
| `trace_sink` | No | `"stdout"` | `"stdout"` or `"otel"` |
| `stream_output` | No | `False` | Default: blocking result vs streaming events |
| `metadata` | No | `{}` | Arbitrary extra data |

## AgentPersonaConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `role` | Yes | — | Job title or role label |
| `goal` | Yes | — | What the agent should accomplish |
| `backstory` | No | `None` | Optional background context |
| `system_prompt` | No | `None` | Full system prompt override (skips template) |
| `system_prompt_template` | No | framework default | Jinja2 template for system prompt |
| `prompt_args` | No | `{}` | Extra Jinja variables from orchestration YAML (e.g. `domain`) |

In YAML orchestration, use `persona.prompt` + `prompt_args` instead of `system_prompt_template` directly. Templates are stored raw at load time and rendered once per LLM turn.

## TurnConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `max_turns` | No | `10` | Max agent loop iterations |
| `max_tool_calls_per_turn` | No | `5` | Cap tool calls per turn (`0` = no cap) |
| `stop_on_empty_tool_calls` | No | `True` | Stop when LLM returns no tool calls |
| `stop_sequences` | No | `[]` | Text sequences that stop the agent (**planned — not enforced in runner yet**) |
| `stop_on_result_type` | No | `True` | Stop when structured result is obtained (**planned — not enforced in runner yet**) |
| `human_in_loop_after_turns` | No | `None` | Pause after N completed turns using the same `pending_interactions` / `resume()` path as client tools (`tool_name="human_in_loop"`) |
| `turn_timeout_seconds` | No | `300` | Per-turn timeout in seconds |

## LLMProviderConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `provider` | No | `openai` | Provider hint for model-string prefixing (`openai`, `anthropic`, `litellm`, `gemini`, `groq`, `ollama`, etc.). **All providers route through the unified `LiteLLMAdapter`.** |
| `model` | No | `gpt-4o` | Model name for the provider |
| `api_key` | No | `""` | Secret API key |
| `base_url` | No | `None` | Custom endpoint (proxies, local servers) |
| `api_version` | No | `None` | Provider-specific API version |
| `context_window_tokens` | No | `128000` | Max context size for budgeting. When a build exceeds this, Nexus first tries RCS compaction, then replaces oversized raw tool bodies with a retry notice, and only then drops whole turns. A user query is always preserved in the final message list. |
| `timeout` | No | `60` | Request timeout in seconds |
| `max_retries` | No | `3` | Retry count on failure |
| `retry_delay` | No | `1.0` | Seconds between retries |
| `extra_headers` | No | `{}` | Extra HTTP headers |
| `default_params` | No | `{}` | Extra params sent to the provider (`max_tokens`, `temperature`, `extra_body`, `reasoning_effort`, `thinking`, …). Anything the model rejects is dropped rather than failing the call. |
| `enable_thinking` | No | `None` | Force a self-hosted model's reasoning on (`True`) or off (`False`). `None` leaves the deployment's own setting alone. |

`base_url` overrides the endpoint; it does **not** choose the adapter. Set `provider` explicitly.

### Reasoning ("thinking")

`enable_thinking` sets `extra_body.chat_template_kwargs.enable_thinking` for models that
read it (Qwen3 and friends behind vLLM, SGLang or a LiteLLM proxy). Anything you put in
`default_params.extra_body` wins over it.

Set `enable_thinking=False` for **voice**: a reasoning model otherwise writes a whole
thinking block before the first speakable word, which wrecks time-to-first-audio.

Leave it at `None` (or `True`) for chat, and reasoning arrives as `reasoning` stream
events, separate from the answer. See [streaming.md](streaming.md#reasoning-thinking).

## AgentGroupConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Group name |
| `description` | No | `None` | Optional description |
| `pattern` | No | `supervisor` | `supervisor`, `pipeline`, `parallel` |
| `members` | No | `[]` | List of `AgentConfig` or nested `AgentGroupConfig` |
| `max_turns` | No | `20` | Total turns across members (enforced by orchestrator) |
| `aggregation_strategy` | No | `supervisor` | For `parallel`: `concat`, `first_complete`, or `vote` (plurality of replies; no extra LLM call). `consensus` is **held** until cost/budget wiring exists |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `supervisor` | No | `None` | Lead member name for supervisor pattern |
| `persist_members` | No | `False` | Persist member chat sessions when `True` |
| `context_sharing` | No | `inherit` | `isolated`, `inherit`, or `shared` for group metadata/state |
| `rcs` | No | disabled | Group-level RCS settings |
| `stream_output` | No | `False` | Default streaming mode |

Groups do **not** have an `llm` field. Each member's `AgentConfig` has its own LLM.

## ContextSummaryConfig

See [context-summary.md](context-summary.md) for the full field table (`summarize_on`, `summary_prompt`, `turns_to_fold`, etc.).

## Related references

- [Memory](memory.md)
- [RAG](rag.md)
- [Context summary](context-summary.md)
- [RCS fields](#runtimecontextsummarizerconfig-rcs) — see RuntimeContextSummarizerConfig below

### RuntimeContextSummarizerConfig (RCS)

RCS keeps long tool outputs from filling the context window. When enabled, every tool schema gets an extra `_context_updates` parameter. The LLM can pass summaries of old tool results through this parameter on its next tool call; the interceptor strips it before the tool runs (transparent to tool authors). Summarized results keep their tool signature but lose their `[TCn]` tag so they are not re-summarized.

A tool call is **never removed** from the context. Each one has exactly two possible states:

| State | Rendered as |
|-------|-------------|
| Not summarized | `[TCn] tool_name(args)` + the full raw response |
| Summarized | `tool_name(args)` + the summary (no tag, so it is not re-summarized) |

To summarize nothing on a given turn, the LLM sends an empty list (`_context_updates: []`) or omits the parameter. Every `summary` it does send must be non-empty text: a missing, null, empty, or `"[]"` summary is treated as "not summarized", leaving that result raw and still eligible on a later turn. Older versions used `"[]"` as a sentinel meaning "drop this result"; sessions stored that way now replay their full raw response.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `enabled` | No | `False` | Turn on inline tool-result summarization |
| `tc_tag_format` | No | `"[TC{n}]"` | Tag format for unsummarized tool call results |
| `tc_tag_include_tool_signature` | No | `True` | Include tool name + args in the tag prefix |
| `context_updates_param_name` | No | `"_context_updates"` | Extra param injected into every tool schema |
| `context_updates_param_description` | No | default | Description text for the injected param |
| `rcs_system_block` | No | default | RCS contract block appended to the system prompt |
| `fallback_compactor.enabled` | No | `False` | Separate LLM call to summarize old results when context overflows |
| `fallback_compactor.trigger_token_threshold` | No | `10000` | Token count that triggers the fallback compactor |
| `fallback_compactor.compact_oldest_n_tcs` | No | `2` | Number of oldest unsummarized TCs to compact per trigger |
| `fallback_compactor.compactor_llm` | No | agent's LLM | Cheaper model for compaction |
| `fallback_compactor.max_tokens_per_summary` | No | `100` | Max tokens per compacted summary |
| `fallback_compactor.prompt_template` | No | default | Custom compaction prompt |

### RCS events

| Event | When |
|------|------|
| `rcs.tc_summarized` | A tool result was summarized inline via `_context_updates` |
| `rcs.context_built` | The context window was built (tagged vs summarized counts) |
| `rcs.compactor_triggered` | The fallback compactor started |
| `rcs.compactor_completed` | The fallback compactor finished (TCs compacted + tokens saved) |
| `rcs.cross_session_tc_reference` | The LLM referenced a TC id that does not belong to this session |

### RCS token accounting

RCS tracks **two** savings metrics:

| Metric | What it measures | Where it lives |
|--------|-----------------|----------------|
| `total_tokens_saved_by_rcs` | **One-time** compression savings — `tokens_raw - tokens_summarized` per TC, counted once at the moment the LLM summarizes it via `_context_updates`. | `AgentSession`, `AgentRunResult`, `AgentGroupResult` |
| `cumulative_input_tokens_saved_by_rcs` | **Recurring** input-token savings — how many input tokens RCS saves *each turn* by having summarized TCs in context instead of their raw versions. A TC summarized in turn N saves input tokens in every subsequent turn that includes it, so this grows monotonically. | `AgentSession`, `AgentRunResult` (`cumulative_input_tokens_saved_by_rcs`), `AgentGroupResult` (`cumulative_tokens_saved_by_rcs`) |

**Why two metrics?** The one-time metric tells you how much each TC was compressed (e.g. "500-token result → 20-token summary"). The cumulative metric tells you the true cost impact: after N turns, the same summarized TC has saved input tokens N times (once per subsequent turn), so the real savings can be many times larger.

Both use the same `TokenCounter`-based formula, so:
- `sum(turn.tokens_saved_this_turn) == session.total_tokens_saved_by_rcs` (one-time)
- `sum(turn.recurring_savings_this_turn) == session.cumulative_input_tokens_saved_by_rcs` (recurring)

Re-summarizing an already-summarized TC counts only marginal savings (previous summary tokens − new summary tokens), preventing double-counting in the one-time metric.

### `token_usage` aggregate on the session

`AgentSession` exposes a computed `token_usage` block that bundles all chat-level token accounting into one place for UI rendering and external analysis:

```json
"token_usage": {
  "total_tokens_in": 12345,
  "total_tokens_out": 678,
  "total_tokens_saved_by_rcs": 4321,
  "cumulative_input_tokens_saved_by_rcs": 9876,
  "rcs_enabled": true
}
```

- `total_tokens_in` / `total_tokens_out` — actual tokens sent to / received from the LLM, summed from the per-turn records (`turn.total_tokens_in` / `turn.total_tokens_out`). RCS is already applied to the inputs, so this is the real spend.
- `total_tokens_saved_by_rcs` / `cumulative_input_tokens_saved_by_rcs` — the two RCS savings metrics above (mirrored from the session counters for a single read).
- `rcs_enabled` — whether RCS was enabled for this chat (set once at run start).

Because `token_usage` is a pydantic `@computed_field`, it is included verbatim in `model_dump(mode="json")` — so the **stored chat JSON blob carries the pre-aggregated values**. External readers (a SQL query like `chatJson->'token_usage'->>'total_tokens_in'`, a script loading the JSON, or a BI tool) can read the metrics directly without summing per-turn fields or loading the model. Inside the app it recomputes on load, so it can never drift from the per-turn data.

## Next steps

- [Runtime control](../guides/runtime-control.md) — external HITL and supervision patterns
- [Runner](agent-runner.md)
- [Tools](tools.md)
- [Skills](skills.md)
