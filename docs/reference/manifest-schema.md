# YAML manifest schema

**Who this is for:** Anyone editing an orchestration YAML file who needs every field and default.

## Key terms

- **Manifest** — The top-level YAML document loaded by `OrchestrationManifest.load()`.
- **Root** — The agent or group name that runs when you call `runtime.run()`.
- **Anchor** — YAML `&name` / `*name` syntax to reuse a block (often for shared LLM settings).

Annotated example: [../assets/complete-manifest.annotated.yaml](../assets/complete-manifest.annotated.yaml).

## Top-level fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `version` | No | `"1"` | Manifest format version |
| `root` | Yes | — | Agent or group name to execute |
| `prompts_module` | No | `{stem}_prompts.py` beside YAML | Python file with `PROMPTS` dict |
| `defaults` | No | empty | Shared blocks merged into agents/groups |
| `storage` | No | `adapter: memory` | Where chat history is saved |
| `plugins` | No | `{}` | Plugin name → `module.path.ClassName` |
| `agents` | No | `{}` | Named agent definitions |
| `groups` | No | `{}` | Named team definitions |

## `defaults` block

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `defaults.agent` | No | `{}` | Merged into every agent (turns, memory, etc.) |
| `defaults.llm` | No | `{}` | Used when an agent omits `llm` |
| `defaults.group` | No | `{}` | Merged into every group |

## Agent fields (under `agents.<name>`)

Agents accept the same fields as `AgentConfig` plus orchestration persona keys:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `llm` | No* | from `defaults.llm` | LLM provider settings (*required unless defaults provide it) |
| `persona.role` | Yes** | — | Agent role label (**when persona block is used) |
| `persona.goal` | Yes** | — | What the agent tries to do |
| `persona.backstory` | No | `None` | Extra background text |
| `persona.prompt` | No | — | Key in `PROMPTS` dict (orchestration) |
| `persona.prompt_args` | No | `{}` | Extra Jinja variables (flattened at render time; stored on persona) |
| `turns` | No | `TurnConfig()` defaults | Loop limits |
| `tool_plugins` | No | `[]` | Allow-list of plugin namespaces |
| `memory` | No | disabled | Cross-session user memory settings |
| `context_summary` | No | disabled | Rolling conversation summary (`summarize_on`) |
| `rcs` | No | disabled | Long-context summarization |
| `skills` | No | disabled | agentskills.io folders |
| `storage` | No | `None` | Per-agent storage fallback |

See [agent-config.md](agent-config.md) for nested fields (`turns`, `memory`, `rcs`, `skills`).

## Group fields (under `groups.<name>`)

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `pattern` | No | `supervisor` | How members run: `supervisor`, `pipeline` (`parallel`/`swarm` fall back to pipeline) |
| `members` | No | `[]` | Agent names, inline agents, or nested group refs |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `max_turns` | No | `20` | Total turns across the group |
| `description` | No | `None` | Human-readable description |
| `stream_output` | No | `False` | Default streaming mode for the group |

## `llm` block (agent or defaults)

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `provider` | No | `openai` | Which LLM adapter to use |
| `model` | No | `gpt-4o` | Model name string |
| `api_key` | Yes for real calls | `""` | API key (use `${ENV:...}` in YAML) |
| `base_url` | No | `None` | Custom API endpoint URL |

Full list: [agent-config.md](agent-config.md#llmproviderconfig).

## Env interpolation

Any YAML string can use:

- `${ENV:VAR_NAME}` — substitute environment variable
- `${ENV:VAR_NAME|fallback}` — use fallback if unset

## Errors you may see

| Error | Cause |
|-------|-------|
| `PromptNotFoundError` | `persona.prompt` key missing from `PROMPTS` |
| `MemberNotFoundError` | Group `members` references unknown name |
| `ReferenceCycleError` | Nested groups reference each other in a loop |

## Next steps

- [Getting started (YAML)](../getting-started.md)
- [Prompts and Jinja](../guides/prompts-jinja.md)
- [Multi-agent](multi-agent.md)
