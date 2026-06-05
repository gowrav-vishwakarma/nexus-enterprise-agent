# Skills

**Who this is for:** Developers using portable skill folders (agentskills.io standard) for specialized workflows.

## Key terms

- **Skill** — A folder with `SKILL.md` instructions the agent can load on demand.
- **Catalog** — Names and descriptions injected into the system prompt at run start.
- **Activation** — Loading the full `SKILL.md` body into context.

## How it works

| Stage | What loads | When |
|-------|------------|------|
| Advertise | Skill name + description | Start of run (`activation_mode` auto or both) |
| Activate | Full `SKILL.md` | Agent calls `skills.load_skill` |
| Execute | Files in `references/`, `assets/` | Agent calls `skills.read_skill_resource` |

## Folder layout

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
| `global_paths` | No | `[NEXUS_SKILLS_ROOT]` | Directories to scan |
| `explicit_skills` | No | `[]` | Skill names to pre-load every run |
| `enabled_skills` | No | `None` | Allowlist; `None` = all discovered |
| `allow_scripts` | No | `False` | Expose script execution tool |
| `allow_tenant_skills` | No | `False` | Phase 2 — per-tenant skill dirs |
| `allow_user_skills` | No | `False` | Phase 2 — per-user skill dirs |

When `enabled=True`, the runner auto-registers the `skills` tool plugin. You do **not** add `"skills"` to `tool_plugins` yourself.

## Activation modes

| Mode | System prompt | Tools |
|------|---------------|-------|
| `auto` | Catalog only | `load_skill`, `read_skill_resource` |
| `explicit` | Full bodies of listed skills | Same |
| `both` | Explicit bodies + catalog for rest | Same |

Per-request skills via `RunContext(metadata={"skills": ["code-review"]})` with `explicit` or `both` mode.

## Phase 1 limits

- Global skills only (manual folder copy)
- Script execution off by default
- Install skills you trust — text is injected into prompts

## Next steps

- [Tools](tools.md)
- [Environment](environment.md) — `NEXUS_SKILLS_ROOT`
