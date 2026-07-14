# YAML manifest schema

**Who this is for:** Anyone editing an orchestration YAML file who needs every field and default.

## Key terms

- **Manifest** — The top-level YAML document loaded by `OrchestrationManifest.load()`.
- **Root** — The agent or group name that runs when you call `runtime.run()`.
- **Anchor** — YAML `&name` / `*name` syntax to reuse a block (often for shared LLM settings).

Annotated examples: [../assets/complete-manifest.annotated.yaml](../assets/complete-manifest.annotated.yaml), [../assets/research_team_prompts.annotated.py](../assets/research_team_prompts.annotated.py).

## Top-level fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `version` | No | `"1"` | Manifest format version |
| `root` | Yes | — | Agent or group name to execute |
| `prompts_module` | No | `{stem}_prompts.py` beside YAML | Python file with `PROMPTS` dict — see [research_team_prompts.annotated.py](../assets/research_team_prompts.annotated.py) |
| `defaults` | No | empty | Shared blocks merged into agents/groups |
| `storage` | No | `adapter: memory` | Where chat history is saved |
| `plugins` | No | `{}` | Plugin name → `module.path.ClassName` |
| `servers` | No | `{}` | Named gRPC media servers (STT/TTS/VAD/LID) — see [server.md](server.md) |
| `agents` | No | `{}` | Named agent definitions |
| `groups` | No | `{}` | Named team definitions |
| `channels` | No | `{}` | Channel name → channel spec (adapter import path, secrets) — see [realtime-agents.md](realtime-agents.md) |

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
| `pattern` | No | `supervisor` | How members run: `supervisor`, `pipeline`, `parallel` (`swarm` falls back to pipeline) |
| `members` | No | `[]` | Agent names, inline agents, or nested group refs |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `max_turns` | No | `20` | Total turns across the group |
| `aggregation_strategy` | No | `supervisor` | For `parallel`: `concat` (labelled join) or `first_complete` |
| `description` | No | `None` | Human-readable description |
| `stream_output` | No | `False` | Default streaming mode for the group |

The `parallel` pattern runs all members concurrently on the same input and
combines their replies (see `aggregation_strategy`). The `voice_team` pattern
(loaded by `RealtimeRuntime`, not the text runtime) wires a voice responder with
an optional context agent — see [realtime-agents.md](realtime-agents.md).

## Realtime agent fields (voice / vision)

A realtime agent is a normal agent plus media keys. These are read by
`RealtimeRuntime` (the text runtime ignores them). The text agent config goes
under an `agent:` block:

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `modality` | No | `voice_cascaded` | `voice_cascaded` (STT→LLM→TTS), `voice_s2s` (speech-to-speech), `vision_text` |
| `duplex` | No | `full` | `half` (IVR, strict turns) or `full` (barge-in) |
| `stt` | No | mock | Speech-to-text: `provider`, `server_ref`, `language`, `sample_rate` |
| `tts` | No | mock | Text-to-speech: `provider`, `server_ref`, `voice`, `sample_rate` |
| `vad` | No | energy | Turn detection: `provider`, `server_ref`, `silence_ms`, `threshold` |
| `lid` | No | — | Per-turn language ID: `provider`, `server_ref`, `fallback_language`, `sample_rate` |
| `s2s` | No | openai_realtime | Speech-to-speech model: `provider`, `model`, `voice` |
| `agent` | Yes | — | The underlying `AgentConfig` (persona, llm, tools, ...) |

See [realtime-agents.md](realtime-agents.md) for voice/channel docs and [server.md](server.md) for every `servers:` / `server_ref` field with examples.

## `servers:` block (gRPC media)

Optional top-level map of named media servers. Keys are **labels** you choose; agents reference them via `server_ref`.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| *(key)* | Yes | — | Arbitrary label (e.g. `indic_stt`, `whisper_lid`) |
| `kind` | Yes | — | `stt`, `tts`, `vad`, or `lid` |
| `engine` | Yes | — | Engine plugin id |
| `host` | No | `127.0.0.1` | Bind / connect address |
| `port` | Yes | — | gRPC port |
| `device` | No | — | `cpu`, `cuda`, … |
| `replicas` | No | `1` | TTS replica count |
| `sample_rate` | No | — | Native audio rate (Hz) |
| `extra` | No | `{}` | Engine-specific options |

Full tables, agent adapter fields, recipes, and Voice Lab two-YAML setup: [server.md](server.md).

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
