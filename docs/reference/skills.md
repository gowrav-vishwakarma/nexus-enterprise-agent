# Skills

**Who this is for:** Developers using portable skill folders (agentskills.io standard) and optional learned skills that persist per tenant/company/user.

## Key terms

- **Skill** — A folder with `SKILL.md` instructions the agent can load on demand.
- **Catalog** — Names and descriptions injected into the system prompt at run start.
- **Activation** — Loading the full `SKILL.md` body into context.
- **Learned skill** — A skill written at runtime (by tools or a subagent) into a skill store.
- **Skill scope** — Which `RunContext` fields partition learned skills (global / company / user).
- **Skill store** — Backend that saves learned skills (`none`, `memory`, `file`, or `custom`).

## How it works (static skills)

| Stage | What loads | When |
|-------|------------|------|
| Advertise | Skill name + description | Start of run (`activation_mode` auto or both) |
| Activate | Full `SKILL.md` | Agent calls `skills.load_skill` |
| Execute | Files in `references/`, `assets/` | Agent calls `skills.read_skill_resource` |

## Folder layout (agentskills.io)

```text
skills/
└── code-review/
    ├── SKILL.md
    ├── references/
    └── assets/
```

Set path with `NEXUS_SKILLS_ROOT` (default `./skills`).

## SkillsConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `enabled` | No | `False` | Turn skills on for this agent |
| `activation_mode` | No | `"auto"` | `"auto"`, `"explicit"`, or `"both"` |
| `global_paths` | No | `[NEXUS_SKILLS_ROOT]` | Directories to scan for static skills |
| `explicit_skills` | No | `[]` | Skill names to pre-load every run |
| `enabled_skills` | No | `None` | Allowlist; `None` = all discovered |
| `allow_scripts` | No | `False` | Expose script execution tool |
| `allow_tenant_skills` | No | `False` | Per-tenant static skill dirs |
| `allow_user_skills` | No | `False` | Per-user static skill dirs |
| `scope` | No | see SkillScopeConfig | Which identity fields partition **learned** skills |
| `store_backend` | No | `"none"` | `"none"`, `"memory"`, `"file"`, or `"custom"` |
| `store_class` | No | `None` | Import path when `store_backend="custom"` |
| `store_config` | No | `{}` | Backend kwargs (e.g. `root` for file store) |
| `retrieval_k` | No | `6` | Max learned skills injected per turn from search |
| `inject_learned` | No | `True` | Inject relevant learned skills into the system prompt |
| `expose_manage_tools` | No | `False` | Register `skill_manage` tools on the main agent |

When `enabled=True`, the runner auto-registers the `skills` tool plugin. You do **not** add `"skills"` to `tool_plugins` yourself. Also do **not** add `"skills"` to a `toolset` allow-list; the runner manages skill tools independently of your registry-defined toolsets.

### SkillScopeConfig

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `keys` | No | `["tenant_id", "company_id", "user_id"]` | Ordered `RunContext` fields that form the learned-skill partition |
| `resolver_class` | No | `None` | Optional import path for a custom `SkillScopeResolver` |

Examples:

| `keys` | Meaning |
|--------|---------|
| `[]` | Global learned skills shared by everyone |
| `["tenant_id"]` | Per tenant |
| `["tenant_id", "company_id"]` | Per company |
| `["tenant_id", "company_id", "user_id"]` | Per user (default) |

See [Skills storage](../guides/skills-storage.md) for resolver and backend examples.

## Activation modes

| Mode | System prompt | Tools |
|------|---------------|-------|
| `auto` | Catalog only | `load_skill`, `read_skill_resource` |
| `explicit` | Full bodies of listed skills | Same |
| `both` | Explicit bodies + catalog for rest | Same |

Per-request skills via `RunContext(metadata={"skills": ["code-review"]})` with `explicit` or `both` mode.

## Learned skills

Learned skills sit beside static agentskills.io folders. They are stored under a **skill scope** and optionally injected each turn.

### Store backends

| `store_backend` | What it does |
|-----------------|--------------|
| `none` | No learned-skill persistence (default) |
| `memory` | In-process dict store (tests / single process) |
| `file` | Folders with `SKILL.md` under a root (agentskills.io layout) |
| `custom` | Your class via `store_class` |

### FileSkillStore layout

With `store_backend: file` and a root path, skills are written as:

```text
{root}/
  {tenant_id}/{company_id}/{user_id}/
    my-skill/
      SKILL.md
  _global/          # when all scope fields are empty
    shared-skill/
      SKILL.md
```

Each `SKILL.md` uses YAML front matter (`name`, `trigger`, `source`, `enabled`, `use_count`) plus a markdown body.

### skill_manage tools

When `expose_manage_tools=True` and a store is configured, the runner registers:

| Tool | What it does |
|------|--------------|
| `skill_manage.upsert` | Create or update a learned skill (`name`, `trigger`, `content`) |
| `skill_manage.list` | List learned skills for the current scope |
| `skill_manage.delete` | Delete by name |
| `skill_manage.disable` | Soft-disable a skill |

Writes are skipped when `RunContext.should_persist` is `False`.

### Injection

When `inject_learned=True`, the runner searches the store (up to `retrieval_k` matches) and appends a “Learned Skills” block to the system prompt.

## Static skills limits

- Install skills you trust — text is injected into prompts
- Script execution off by default
- Tenant/user static folders require `allow_tenant_skills` / `allow_user_skills`

## Next steps

- [Skills storage guide](../guides/skills-storage.md)
- [Tools](tools.md)
- [Environment](environment.md) — `NEXUS_SKILLS_ROOT`
- [Run context](run-context.md)
