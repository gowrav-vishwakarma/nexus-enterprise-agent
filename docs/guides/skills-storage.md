# Skills storage (learned skills)

**Who this is for:** Developers who want agents to save and reuse learned skills per tenant, company, or user.

## Key terms

- **Learned skill** — Instructions saved at runtime (not only shipped as static folders).
- **Skill scope** — The partition key derived from `RunContext` (global / company / user).
- **Store backend** — Where learned skills live: memory, files, or your own class.

Static agentskills.io folders are unchanged. This guide covers the **learned** path. Full field tables: [skills.md](../reference/skills.md).

## Why scope matters

Without a partition, every customer would share the same learned skills. The **scope resolver** builds a `SessionScope` from selected `RunContext` fields. The skill store uses that scope as a bucket key.

## Scope resolver

`SkillsConfig.scope` is a `SkillScopeConfig`:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `keys` | No | `["tenant_id", "company_id", "user_id"]` | Which identity fields form the partition |
| `resolver_class` | No | `None` | Custom `SkillScopeResolver` import path |

### Common patterns

| Goal | Config |
|------|--------|
| Shared by everyone | `scope: { keys: [] }` |
| Per tenant | `scope: { keys: [tenant_id] }` |
| Per company | `scope: { keys: [tenant_id, company_id] }` |
| Per user (default) | `scope: { keys: [tenant_id, company_id, user_id] }` |

```python
from nexus.skills.config import SkillsConfig
from nexus.skills.scope import SkillScopeConfig

skills = SkillsConfig(
    enabled=True,
    store_backend="file",
    store_config={"root": "./learned_skills"},
    scope=SkillScopeConfig(keys=["tenant_id", "company_id"]),
    inject_learned=True,
    retrieval_k=6,
    expose_manage_tools=True,
)
```

YAML:

```yaml
skills:
  enabled: true
  store_backend: file
  store_config:
    root: ./learned_skills
  scope:
    keys: [tenant_id, company_id]
  inject_learned: true
  retrieval_k: 6
  expose_manage_tools: true
```

Pass matching identity on every run:

```python
RunContext(tenant_id="acme", company_id="co-1", user_id="u-42")
```

## File vs memory backends

| Backend | When to use | Durability |
|---------|-------------|------------|
| `memory` | Unit tests, single-process demos | Lost when the process exits |
| `file` | Dev and single-server apps | Survives restarts; agentskills.io `SKILL.md` folders |
| `custom` | Your database or object store | You implement `SkillStore` |

### Memory

```yaml
skills:
  enabled: true
  store_backend: memory
  expose_manage_tools: true
```

Uses `InMemorySkillStore` (dict keyed by scope path segments).

### File

```yaml
skills:
  enabled: true
  store_backend: file
  store_config:
    root: ./learned_skills
  scope:
    keys: [tenant_id, company_id, user_id]
```

`FileSkillStore` writes:

```text
./learned_skills/
  acme/co-1/u-42/
    invoice-tips/
      SKILL.md
```

Each file has YAML front matter plus the skill body — the same layout as static agentskills.io skills, so you can inspect and edit them by hand.

### Custom

```yaml
skills:
  enabled: true
  store_backend: custom
  store_class: myapp.skills.PostgresSkillStore
  store_config:
    dsn: ${ENV:DATABASE_URL}
```

Implement the `SkillStore` protocol: `search`, `upsert`, `list`, `delete`, `disable`, `get` — each taking a `SessionScope`.

## Managing skills from the agent

With `expose_manage_tools: true`, the model can call:

- `skill_manage.upsert` — create/update
- `skill_manage.list` — list for current scope
- `skill_manage.delete` / `skill_manage.disable`

Cron and subagent runs (`is_cron` / `is_subagent`, or `persistable=False`) skip durable writes via `should_persist`.

## Injection flow

1. Resolve scope from `RunContext`.
2. Search the store (query from the user message / context), up to `retrieval_k`.
3. If `inject_learned` is true, append a “Learned Skills” markdown block to the system prompt.

## Next steps

- [Skills reference](../reference/skills.md)
- [Run context](../reference/run-context.md)
- [Custom storage adapter](custom-storage-adapter.md) — same scope idea for chat history
