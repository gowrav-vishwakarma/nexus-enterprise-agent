# Agent config reference

**Who this is for:** Developers building `AgentConfig` in Python or YAML who need every field and default.

## Key terms

- **Persona** — Role, goal, and backstory that shape the system prompt.
- **Turn** — One cycle of: send messages to LLM → maybe call tools → save results.
- **RCS** — Runtime Context Summarization; keeps long tool outputs from filling the context window.
- **Memory** — Durable user facts stored across chat threads (cross-session).

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
| `human_in_loop_after_turns` | No | `None` | Pause for human input after N turns (**planned — not enforced in runner yet**; use external HITL — see [runtime-control.md](../guides/runtime-control.md)) |
| `turn_timeout_seconds` | No | `300` | Per-turn timeout in seconds |

## LLMProviderConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `provider` | No | `openai` | Provider hint for model-string prefixing (`openai`, `anthropic`, `litellm`, `gemini`, `groq`, `ollama`, etc.). **All providers route through the unified `LiteLLMAdapter`.** |
| `model` | No | `gpt-4o` | Model name for the provider |
| `api_key` | No | `""` | Secret API key |
| `base_url` | No | `None` | Custom endpoint (proxies, local servers) |
| `api_version` | No | `None` | Provider-specific API version |
| `context_window_tokens` | No | `128000` | Max context size for budgeting |
| `timeout` | No | `60` | Request timeout in seconds |
| `max_retries` | No | `3` | Retry count on failure |
| `retry_delay` | No | `1.0` | Seconds between retries |
| `extra_headers` | No | `{}` | Extra HTTP headers |
| `default_params` | No | `{}` | Extra params sent to the provider (`max_tokens`, `temperature`, `extra_body`, …). Use `extra_body.chat_template_kwargs.enable_thinking: false` for voice with Qwen3. |

`base_url` overrides the endpoint; it does **not** choose the adapter. Set `provider` explicitly.

## AgentGroupConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Group name |
| `description` | No | `None` | Optional description |
| `pattern` | No | `supervisor` | `supervisor`, `pipeline`, `parallel`, `swarm` |
| `members` | No | `[]` | List of `AgentConfig` or nested `AgentGroupConfig` |
| `max_turns` | No | `20` | Total turns across members |
| `aggregation_strategy` | No | `supervisor` | How to combine results |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `rcs` | No | disabled | Group-level RCS settings |
| `stream_output` | No | `False` | Default streaming mode |

Groups do **not** have an `llm` field. Each member's `AgentConfig` has its own LLM.

## ContextSummaryConfig

See [context-summary.md](context-summary.md) for the full field table (`summarize_on`, `summary_prompt`, `turns_to_fold`, etc.).

## Related references

- [Memory](memory.md)
- [Context summary](context-summary.md)
- [RCS fields](#runtimecontextsummarizerconfig-rcs) — see RuntimeContextSummarizerConfig below

### RuntimeContextSummarizerConfig (RCS)

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `enabled` | No | `False` | Turn on inline tool-result summarization |
| `tc_tag_format` | No | `"[TC{n}]"` | Tag format for tool call results |
| `tc_tag_include_tool_signature` | No | `True` | Include tool name in tag |
| `context_updates_param_name` | No | `"_context_updates"` | Extra param injected into tool schemas |
| `empty_summary_sentinel` | No | `"[]"` | Value meaning "drop this result from context" |
| `fallback_compactor.enabled` | No | `False` | Separate LLM call to summarize old results |

## Next steps

- [Runtime control](../guides/runtime-control.md) — external HITL and supervision patterns
- [Runner](agent-runner.md)
- [Tools](tools.md)
- [Skills](skills.md)
