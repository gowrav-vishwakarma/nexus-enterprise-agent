# Context summary

**Who this is for:** Developers running long single-chat sessions who need to compress older turns without losing narrative.

## Key terms

- **summary_text** — Rolling summary of folded turns, stored on `AgentSession` and injected into the system prompt.
- **summarize_on** — Fraction of `llm.context_window_tokens` that triggers summarization (e.g. `0.8` = 80%).
- **Context summarizer** — Optional gated LLM call that folds oldest unfoldable turns into `summary_text`.

## When to use

| Need | Use |
|------|-----|
| Compress tool outputs | [RCS](agent-config.md) |
| Compress chat turns when window fills | `context_summary` (this page) |
| Remember user across chats | [Memory](memory.md) (`user_memory`) |

Within one chat, `session.turns` holds full history until summarization folds the oldest turns. RCS handles tool blobs; context summary handles turn-level narrative.

## ContextSummaryConfig

Set on `AgentConfig` as `context_summary`:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `summarize_on` | No | `None` (disabled) | Trigger when `context_tokens / context_window >=` this value |
| `summary_prompt` | No | default prompt | Custom summarizer prompt |
| `summary_llm` | No | agent's LLM | Cheaper model for summarization |
| `turns_to_fold` | No | `2` | Oldest unfoldable turns to fold per trigger |
| `max_summary_chars` | No | `4000` | Max length of rolling `summary_text` |
| `inject_into_prompt` | No | `True` | Show `summary_text` in system prompt |

When `summarize_on` is `None`, the summarizer is fully disabled.

## Prompt injection

`summary_text` is a Jinja variable in the same single render as `user_memory` and persona fields. The default system template includes:

```jinja
{% if summary_text %}
## Conversation Summary
{{ summary_text }}
{% endif %}
```

Custom templates without this block still receive the summary via `SummaryPromptInjector` (same pattern as `user_memory`).

## Next steps

- [Agent config](agent-config.md)
- [Memory](memory.md)
- [Prompt templates](../guides/prompts-jinja.md)
