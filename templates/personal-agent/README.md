# Personal agent starter

A single-operator agent with durable memory and a terminal chat loop — the Nexus
equivalent of a personal assistant product.

```bash
export OPENAI_API_KEY=sk-...
uv run python templates/personal-agent/main.py
```

State lives under `./agent-data` (override with `AGENT_DATA_ROOT`), so notes and
remembered facts survive a restart.

## What [main.py](main.py) shows

- One operator means a fixed `RunContext(user_id="me", should_persist=True)` instead
  of one derived per request. Contrast with [../saas-chat](../saas-chat).
- `MemoryConfig(enabled=True)` carries facts across sessions, so preferences learned
  today apply tomorrow — see [memory.md](../../docs/reference/memory.md).
- SQLite session storage under a local data root.
- Two file-backed tools, and a streaming loop that prints tokens as they arrive.

Skills, which let the agent accumulate reusable procedures, are the natural next
addition: [skills.md](../../docs/reference/skills.md).
