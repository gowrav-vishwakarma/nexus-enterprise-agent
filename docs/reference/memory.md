# Memory

**Who this is for:** Developers who want agents to remember facts about a user across chat threads.

## Key terms

- **User memory** — Durable key/value facts about a user, stored outside the chat session JSON.
- **Cross-session memory store** — The database or cache that holds user memory (`CrossSessionMemoryStore`).
- **Curator** — An optional extra LLM call that extracts facts after each turn and writes them to the store.
- **Chat history** — The full turn-by-turn conversation in `AgentSession.turns` (within one chat thread).
- **RCS** — Runtime Context Summarization; compresses tool results in context. Not a fact store.

## Two mechanisms

| Question | Mechanism | Survives new chat thread? |
|----------|-----------|---------------------------|
| Remember within this chat? | `session.turns` + optional RCS summaries | No (same `session_id` only) |
| Remember this user next time? | `memory` config + cross-session store | Yes (with persistent store) |
| Search a large document set? | Your own RAG tool | N/A (not built into Nexus) |

Within a single chat, the conversation history is the context. For long chats, enable [RCS](agent-config.md) to compress tool outputs and optional [context summary](context-summary.md) to fold older turns into `summary_text`.

## MemoryConfig

Set on `AgentConfig` as `memory`:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `enabled` | No | `False` | Master switch; if False, no curator runs and facts are not injected |
| `namespace` | No | `""` | Isolation key for facts (empty = agent name) |
| `max_entities` | No | `100` | Max stored facts (oldest dropped beyond cap) |
| `extract_after_each_turn` | No | `True` | Run curator after each turn |
| `extract_at_end` | No | `False` | Run curator once more after `run()` finishes |
| `extraction_interval` | No | `0` | Run every N turns instead (0 = use `extract_after_each_turn` only) |
| `inject_into_prompt` | No | `True` | Show `user_memory` in system prompt |
| `curator_llm` | No | agent's LLM | Cheaper model for extraction |
| `curator_prompt` | No | default prompt | Custom curator prompt |
| `curator_agent` | No | `None` | Full `AgentConfig` used as curator (advanced) |
| `max_conversation_chars` | No | `6000` | Max chars fed to curator |

## Requirements

When `memory.enabled` is True, you also need:

1. `cross_session_memory_store` on `AgentRunner` / orchestrator
2. `RunContext.user_id` on every run

If either is missing, load and write are skipped silently.

## Built-in cross-session stores

| Store | When to use |
|-------|-------------|
| `InMemoryCrossSessionMemoryStore` | Tests; lost on exit |
| `SQLiteCrossSessionMemoryStore` | Single-server apps |

Implement your own store with `load`, `save`, `merge_entities` for PostgreSQL/Redis.

## Prompt injection

Facts appear in the system prompt as the Jinja variable `user_memory` (a dict of key/value strings). The default template includes an "About this user" block when `user_memory` is non-empty.

`user_memory` is resolved in the same single Jinja render as persona fields, run context, and `summary_text` (see [prompt templates guide](../guides/prompts-jinja.md)).

`MemoryPromptInjector` appends the same block when a custom `system_prompt` override omits Jinja memory sections (fallback for non-template overrides). The runner loads `user_memory` at run start, passes it on every context build, and reloads after the curator updates the store.

## When to skip memory

If you only need within-chat context, rely on chat history and RCS. Memory is fully opt-out: set `memory.enabled=False` (the default).

## Note on `MemoryStorageAdapter`

`MemoryStorageAdapter` is the in-process **session** storage backend (chat history). It is unrelated to the memory feature described here.

## Next steps

- [Agent config](agent-config.md)
- [Storage](storage.md)
- [Design spec](../NEXUS_AGENT_PRD.md) (historical; may describe older memory shapes)
