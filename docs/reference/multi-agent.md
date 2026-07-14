# Multi-agent teams

**Who this is for:** Developers running more than one agent in supervisor or pipeline patterns.

## Key terms

- **Group** — `AgentGroupConfig` or a `groups` entry in YAML; wires members and pattern.
- **Supervisor** — One agent delegates work to others via `delegate_to_*` tools.
- **Pipeline** — Agents run in order; each gets the previous agent's final text as input.
- **Member** — One agent inside a group.

## Patterns

| Pattern | Status | What happens |
|---------|--------|--------------|
| `supervisor` | Implemented | Lead agent delegates to members |
| `pipeline` | Implemented | Members run sequentially |
| `parallel` | Implemented | All members run on the same input; outputs merged per `aggregation_strategy` |
| `swarm` | Not yet | Falls back to pipeline with warning |

## AgentGroupConfig

Groups do **not** have an `llm` field. Each member's `AgentConfig` has its own LLM.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Group name |
| `pattern` | No | `supervisor` | Orchestration pattern |
| `members` | No | `[]` | Agents or nested groups |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `max_turns` | No | `20` | Total turns across members |

## Member chat ids

At orchestrator init: `{session_id_prefix}{group_session_id}_{member.name}`

Example: `team_group-1_researcher`, `team_group-1_analyst`.

Set `RunContext.session_id` **before** creating `AgentOrchestrator` or `OrchestrationRuntime`.

## Pipeline handoff

Member N+1 receives member N's **`final_response` string** as its `user_message` — not the full chat log.

## Nested groups (YAML)

```yaml
groups:
  analysis_pipeline:
    pattern: pipeline
    members: [researcher, analyst]
  research_team:
    pattern: supervisor
    members: [supervisor, analysis_pipeline]
```

## Loading history for a UI

```python
from nexus.session.manager import SessionManager

view = await manager.load_session_group(
    root_session_id="group-sess-1",
    tenant_id="acme",
    user_id="user-42",
    pattern="pipeline",
    member_order=["researcher", "analyst"],
)
```

HTTP example in [SaaS guide](../guides/saas-example.md).

## What is shared vs not

| Kind | Shared by default? |
|------|-------------------|
| `tenant_id`, `user_id` | Yes |
| `metadata` | Yes |
| Tool registry | Only if you pass the same instance |
| Chat history | No — separate JSON per member |
| LLM config | No — per member |

## Next steps

- [Pipelines guide](../guides/pipelines.md) — when to use supervisor vs pipeline vs parallel
- [Runtime control](../guides/runtime-control.md) — delegation vs deterministic workflows
- [Getting started (YAML)](../getting-started.md)
- [Storage](storage.md)
- [Manifest schema](manifest-schema.md)
