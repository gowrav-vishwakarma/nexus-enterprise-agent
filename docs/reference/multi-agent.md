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
| `parallel` | Implemented | All members run on the same input; outputs merged per `aggregation_strategy` (`concat`, `first_complete`, `vote`) |

## AgentGroupConfig

Groups do **not** have an `llm` field. Each member's `AgentConfig` has its own LLM.

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Group name |
| `pattern` | No | `supervisor` | Orchestration pattern |
| `members` | No | `[]` | Agents or nested groups |
| `session_id_prefix` | No | `""` | Prefix for member chat ids |
| `supervisor` | No | `None` | Lead member for `supervisor` pattern (else name heuristic) |
| `persist_members` | No | `False` | When `False`, members run with `is_subagent` and skip durable chat persistence |
| `context_sharing` | No | `inherit` | `isolated`, `inherit`, or `shared` (write-back to group after each member) |
| `max_turns` | No | `20` | Total turns across members (**enforced** by the orchestrator) |
| `aggregation_strategy` | No | `supervisor` | For `parallel`: `concat`, `first_complete`, or `vote` |

## Member chat ids

At orchestrator init: `{session_id_prefix}{group_session_id}_{member.name}`

Example: `team_group-1_researcher`, `team_group-1_analyst`.

Set `RunContext.session_id` **before** creating `AgentOrchestrator` or `OrchestrationRuntime`.

Pass `event_emitter=` on `AgentOrchestrator` (or on `OrchestrationRuntime.from_manifest()`) to fan the same observability hook out to every member `AgentRunner` and nested group. You do not attach emitters to members yourself when you use the orchestrator.

Member runners get `RunContext.is_subagent=True` by default (`persist_members=False`), so their chat history is not written to storage. Set `persist_members: true` on the group to keep separate member session files.

Supervisor groups auto-register `supervisor.delegate_to_{member}` tools and **auto-grant** them to the lead agent even when the lead uses a narrow `toolset`. Optional YAML: `supervisor: lead_agent_name`.

Python-only example: [run_team_python.py](../../examples/orchestration/run_team_python.py).

## Parallel aggregation

| Strategy | Extra LLM call? | What it does |
|----------|-----------------|--------------|
| `concat` | No | Labelled join of every member's `final_response` |
| `first_complete` | No | First finished member wins |
| `vote` | No | Plurality of identical `final_response` strings (`Counter.most_common`) |
| `consensus` | Yes (held) | Would ask another model to merge replies. **Not shipped** until per-tenant cost/budget wiring exists, because that extra call is billed to the tenant |

```yaml
groups:
  review_panel:
    pattern: parallel
    aggregation_strategy: vote
    members: [reviewer_a, reviewer_b, reviewer_c]
```

## Pipeline handoff

Member N+1 receives member N's **`final_response` string** as its `user_message` — not the full chat log.

With `context_sharing: shared`, members also share **`RunContext.state`** and **`RunContext.metadata`**: each member run syncs down from the group before it starts and merges back after it finishes, so the next member (and the system prompt via Jinja) can see structured checkpoint data — not only the previous agent's text reply.

## Context sharing (`context_sharing`)

| Mode | Behavior |
|------|----------|
| `isolated` | Members get identity + services only; empty `metadata`/`state` |
| `inherit` (default) | Group `metadata`/`state` copied to each member before it runs; member writes stay local |
| `shared` | Same as `inherit`, plus member bags merge back into the group after each run (pipeline / supervisor) |

Sync runs at **delegation time**, not only at orchestrator construction, so a supervisor can update group state and specialists see it on the next `delegate_to_*` call.

Members receive a `metadata.nexus_delegation` breadcrumb (group name, member name, optional `delegated_by`). The default system prompt template includes a short **Delegated task** section when that key is present.

**Supervisor state handoff:** the lead agent's tools call `ctx.set_state(...)` on the member `RunContext` (same object the runner uses). Before each delegate, the orchestrator merges the supervisor's live state into the group context and syncs down to the specialist. No extra LLM tool parameters are required.

**Parallel + `shared`:** members receive a down-sync before they run, but write-back is skipped (concurrent races). Use pipeline or supervisor for shared mutable state.

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
from nexus.session.scope import SessionScope

view = await manager.load_session_group(
    root_session_id="group-sess-1",
    scope=SessionScope(tenant_id="acme", user_id="user-42"),
    pattern="pipeline",
    member_order=["researcher", "analyst"],
)
```

HTTP example in [SaaS guide](../guides/saas-example.md).

## What is shared vs not

| Kind | Shared by default? |
|------|-------------------|
| `tenant_id`, `user_id`, `company_id`, `auth`, `channel`, services | Yes (via `RunContext.derive_child`) |
| `metadata`, `state` | Yes when `context_sharing` is `inherit` or `shared` (sync at run time) |
| Tool registry | Only if you pass the same instance |
| Chat history | No — separate JSON per member (unless `persist_members: true`) |
| LLM config | No — per member |

## Next steps

- [Pipelines guide](../guides/pipelines.md) — when to use supervisor vs pipeline vs parallel
- [Runtime control](../guides/runtime-control.md) — delegation vs deterministic workflows
- [Getting started (YAML)](../getting-started.md)
- [Storage](storage.md)
- [Manifest schema](manifest-schema.md)
