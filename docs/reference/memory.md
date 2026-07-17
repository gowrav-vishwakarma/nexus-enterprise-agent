# Memory

**Who this is for:** Developers who want agents to remember facts about a user across chat threads.

## Key terms

- **User memory** — Durable key/value facts about a user, stored outside the chat session JSON.
- **Cross-session memory store** — The database or cache that holds user memory (`CrossSessionMemoryStore`).
- **Named store** — A labeled bucket inside memory (for example `user` vs `notes`) with its own inject policy.
- **Curator** — An optional extra LLM call that extracts facts after each turn and writes them to the store.
- **Memory tools** — `memory.write` / `search` / `list` / `remove` the agent can call when `expose_tools` is on.
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
| `expose_tools` | No | `True` | When enabled, auto-register the `memory` tool plugin |
| `namespace` | No | `""` | Isolation key for facts (empty = agent name) |
| `stores` | No | `[]` | Named stores; empty = single default store |
| `max_entities` | No | `100` | Max stored facts (oldest dropped beyond cap) |
| `extract_after_each_turn` | No | `True` | Run curator after each turn |
| `extract_at_end` | No | `False` | Run curator once more after `run()` finishes |
| `extraction_interval` | No | `0` | Run every N turns instead (0 = use `extract_after_each_turn` only) |
| `inject_into_prompt` | No | `True` | Show `user_memory` in system prompt |
| `curator_llm` | No | agent's LLM | Cheaper model for extraction |
| `curator_prompt` | No | default prompt | Custom curator prompt |
| `curator_agent` | No | `None` | Full `AgentConfig` used as curator (advanced) |
| `max_conversation_chars` | No | `6000` | Max chars fed to curator |

## MemoryStoreConfig (named stores)

Use `stores` when you want more than one bucket (profile vs agent notes):

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Store name, e.g. `user` or `memory` |
| `description` | No | `""` | Shown in prompts / tools |
| `inject` | No | `"always"` | `"always"` = inject into system prompt; `"on_recall"` = only via tool search |
| `char_budget` | No | `0` | Soft char budget for always-injected stores (`0` = no budget) |
| `max_entries` | No | `100` | Max keys in this store |

```python
from nexus.config.memory import MemoryConfig, MemoryStoreConfig

memory = MemoryConfig(
    enabled=True,
    expose_tools=True,
    stores=[
        MemoryStoreConfig(name="user", inject="always", description="Stable user profile"),
        MemoryStoreConfig(name="notes", inject="on_recall", description="Searchable notes"),
    ],
)
```

- **`inject="always"`** — Facts appear in the system prompt at run start (subject to `inject_into_prompt`). The runner loads **every** always-inject store (namespace `base` or `base:{name}`) and merges them. With more than one store, keys are prefixed as `{store}/{key}`. Soft `char_budget` trims what is injected (does not delete from the store).
- **`inject="on_recall"`** — Facts stay out of the prompt until the agent calls `memory.search` / `memory.list`.

When `stores` is empty, tools and inject use a single store named `default` (base namespace only).

## Memory tool plugin

When `enabled=True` and `expose_tools=True`, the runner registers the `memory` plugin:

| Tool | What it does |
|------|--------------|
| `memory.write` | Save a durable fact (`key`, `value`, optional `store`) |
| `memory.search` | Substring search in a store (`query`, optional `store`, `k`) |
| `memory.list` | List all facts in a store |
| `memory.remove` | Delete a fact by key |

Writes are skipped when `RunContext.user_id` is missing or `should_persist` is `False` (cron / subagent / `persistable=False`).

## Isolation scope

Cross-chat memory is **not** shared across an entire tenant. Facts are stored per **tenant + user + namespace** (and per named store as a namespace suffix). Custom stores may also scope by **company** via the optional `company_id` argument on `load` / `save` / `merge_entities` (passed from `RunContext.company_id`).

| Scope | Shared across users in the same tenant? |
|-------|----------------------------------------|
| Tenant only | No |
| Tenant + user | Yes (this is the unit of memory) |
| Tenant + company + user | Yes, when the custom store uses `company_id` |
| Chat thread (`session_id`) | Yes — a user’s facts follow them into new threads |
| Agent (`memory.namespace`, or agent name by default) | No — each agent keeps its own fact set |
| Named store | No — `user` and `notes` are separate namespaces |

Pass `RunContext.tenant_id` and a stable `RunContext.user_id` on every run. In a SaaS API, map these from headers such as `X-Tenant-ID` and `X-User-ID` (see [SaaS example](../guides/saas-example.md)).

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
| `PostgreSQLCrossSessionMemoryStore` | Shared Postgres |
| `RedisCrossSessionMemoryStore` | Shared Redis |

Implement your own store with `load`, `save`, `merge_entities` for product tables (optional `search` for richer `memory.search`). Set `SessionStorageConfig.custom_memory_adapter_class` or pass the instance to `AgentRunner`. See [Custom memory stores](../guides/custom-memory-store.md).

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
- [Custom memory stores](../guides/custom-memory-store.md)
- [Run context](run-context.md) — `should_persist` and identity fields
- [Design spec](../NEXUS_AGENT_PRD.md) (historical; may describe older memory shapes)
