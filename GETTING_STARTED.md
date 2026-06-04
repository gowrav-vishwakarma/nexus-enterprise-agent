# Getting Started — Assemble and Run a Nexus Agent

Nexus is built around one idea: **describe an agent in config, hand that config to a runner, call `run()`**. No global LLM settings, no shared agent singleton. Each `AgentConfig` carries its own provider, model, tools, storage, and limits.

For a full multi-tenant SaaS layout (plans, tenants, FastAPI), see [saas_integration_guide.md](saas_integration_guide.md) and [examples/nexus_saas_api.py](examples/nexus_saas_api.py).

---

## The three pieces

| Piece | What it is | You create it when… |
|-------|------------|---------------------|
| **Agent config** | `AgentConfig` — name, persona, **LLM provider**, turns, tools, memory, storage | You define *what* the agent is |
| **Tool registry** | `ToolRegistry` — registered `@tool` functions or `@tool_plugin` classes | The agent can call tools |
| **Runner** | `AgentRunner` — runs the turn loop (LLM → tools → repeat) | You are ready to execute |

```
  AgentConfig          ToolRegistry (optional)
       │                      │
       └──────────┬───────────┘
                  ▼
            AgentRunner
                  │
                  ▼
         await runner.run("user message")
```

Each config can use a **different** `LLMProviderConfig` (OpenAI, Anthropic, LiteLLM proxy, LM Studio, etc.). That is how you give one agent GPT-4o and another Claude on the same app — two configs, two runners (or one group — see below).

---

## Minimal single-agent system

### 1. Install

```bash
uv pip install -e .
# For the SaaS API example only:
uv pip install fastapi uvicorn python-dotenv
```

### 2. Set LLM credentials (your app reads env; Nexus does not)

Copy `.env.example` to `.env` and fill in keys, or pass secrets directly in code.

For a local OpenAI-compatible server (LiteLLM, LM Studio):

```env
NEXUS_LLM_PROVIDER=openai
NEXUS_LLM_BASE_URL=http://localhost:4000
NEXUS_LLM_API_KEY=not-needed
NEXUS_LLM_MODEL=gpt-4o-mini
```

### 3. Define config → runner → run

```python
import asyncio
from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentPersonaConfig, TurnConfig
from nexus.config.llm import LLMProviderConfig
from nexus.config.storage import SessionStorageConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry
from nexus.tools.decorators import tool

@tool(name="echo")
def echo(text: str) -> str:
    """Echo back the input."""
    return text

def build_my_agent() -> AgentConfig:
    return AgentConfig(
        name="assistant",
        llm=LLMProviderConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key=SecretStr("sk-..."),  # or read from os.environ in your factory
            # base_url="http://localhost:4000",  # optional: custom endpoint
        ),
        persona=AgentPersonaConfig(
            role="Helpful assistant",
            goal="Answer clearly and use tools when useful.",
        ),
        turns=TurnConfig(max_turns=10, max_tool_calls_per_turn=5),
        storage=SessionStorageConfig(
            adapter="memory",  # or "sqlite" / "postgresql" for persistence
            adapter_config={"max_sessions": 100},
        ),
        tool_plugins=[],  # use registry below; list plugin *names* if using @tool_plugin
    )

async def main():
    config = build_my_agent()

    registry = ToolRegistry()
    registry.register_tool(echo)

    runner = AgentRunner(
        config=config,
        tool_registry=registry,
        run_context=RunContext(tenant_id="demo", session_id="sess-1"),
    )

    result = await runner.run(
        user_message="Echo hello",
        session_id="sess-1",
    )
    print(result.final_response)
    print("turns:", result.turns_used)

if __name__ == "__main__":
    asyncio.run(main())
```

**Assembly checklist**

1. Build `AgentConfig` (include `llm=LLMProviderConfig(...)` per agent).
2. Optionally build `ToolRegistry` and register tools.
3. `AgentRunner(config=..., tool_registry=..., run_context=...)`.
4. `await runner.run(user_message=..., session_id=...)`.

---

## Per-config providers (the simple rule)

Put the provider on **each** `AgentConfig`, not in a global setting:

```python
researcher = AgentConfig(
    name="researcher",
    llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key=...),
    ...
)

writer = AgentConfig(
    name="writer",
    llm=LLMProviderConfig(provider="anthropic", model="claude-3-5-sonnet-20241022", api_key=...),
    ...
)
```

In production, a small **config factory** (like `NexusTenantConfigFactory` in the SaaS example) maps tenant/plan → `LLMProviderConfig` + storage + tool allow-list, then returns `AgentConfig`.

---

## Multi-agent groups: each member brings its own provider

`AgentGroupConfig` does **not** define an LLM for the whole group. It only defines orchestration: `pattern`, `members`, `max_turns`, group-level `rcs`, etc.

**Providers live on each `AgentConfig` in `members`.** Build one full config per agent (each with its own `llm=LLMProviderConfig(...)`), then pass those configs into the group:

```python
from pydantic import SecretStr
from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.tools.context import RunContext

# Member 1: OpenAI for search-heavy work
researcher_cfg = AgentConfig(
    name="researcher",
    llm=LLMProviderConfig(
        provider="openai",
        model="gpt-4o",
        api_key=SecretStr("sk-openai-..."),
    ),
    persona=AgentPersonaConfig(role="Researcher", goal="Gather facts with web search."),
    tool_plugins=["web_search"],
)

# Member 2: Anthropic for analysis
analyst_cfg = AgentConfig(
    name="analyst",
    llm=LLMProviderConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        api_key=SecretStr("sk-ant-..."),
    ),
    persona=AgentPersonaConfig(role="Analyst", goal="Structure findings into a report."),
    tool_plugins=["database"],
)

# Group = list of AgentConfigs (or nested AgentGroupConfigs), not a shared LLM block
group = AgentGroupConfig(
    name="research_pipeline",
    pattern="pipeline",
    members=[researcher_cfg, analyst_cfg],  # each member keeps its own llm
    max_turns=20,
    # Optional: group-level RCS may reference an LLM for compaction only (see rcs docs)
)

orchestrator = AgentOrchestrator(
    config=group,
    tool_registry=registry,
    storage_config=storage_config,
    run_context=RunContext(tenant_id="acme", session_id="group-sess-1"),
)

result = await orchestrator.run(
    user_message="Analyze Q4 revenue",
    session_id="group-sess-1",
)
```

The orchestrator creates one `AgentRunner` per member; each runner uses **that member’s** `config.llm` (see `AgentOrchestrator._init_members` in the codebase). Member session IDs are derived from the group `RunContext` (e.g. `{prefix}{session_id}_researcher`).

Same tenant, different models per role (SaaS example style): call your factory twice with different `build_llm_config` / model overrides — still two `AgentConfig` objects in `members`, as in `examples/nexus_saas_api.py` (`researcher_cfg` vs `analyst_cfg`).

| Config type | Has `llm`? | Role |
|-------------|------------|------|
| `AgentConfig` | Yes — **this agent’s** provider/model/key | Runnable agent |
| `AgentGroupConfig` | No (only optional group `rcs` compactor LLM) | Wires `members` + `pattern` |

---

## `RunContext`: what it is and when you need it

`RunContext` is **per request / per run**, not part of `AgentConfig`. It carries who and which conversation this execution belongs to, and optional bag-of-data for tools.

```python
RunContext(
    tenant_id="acme",      # stored on new sessions; used for multi-tenant storage filters
    user_id="user-42",     # same
    session_id="sess-1",   # default session if you omit session_id on run()
    request_id="req-9",    # tracing / correlation (your choice)
    metadata={"plan": "pro"},  # arbitrary; tools can read via ctx.get("plan")
)
```

### What the framework uses it for

1. **Sessions** — When creating a session, `AgentRunner` passes `tenant_id` and `user_id` from `RunContext` into storage (see `create_session` in `agent_runner.py`). Shared DB adapters can scope rows by tenant.
2. **Session ID default** — If you call `run()` without `session_id`, the runner uses `run_context.session_id` (and writes the resolved id back onto the context).
3. **Tool dependency injection** — If a tool declares a `RunContext` parameter, the registry injects the same context on every tool call:

```python
@tool(name="tenant_settings")
def tenant_settings(ctx: RunContext) -> str:
    return f"Settings for tenant {ctx.tenant_id}"
```

4. **Multi-agent** — You pass one group-level `RunContext` into `AgentOrchestrator`; it clones it per member (same `tenant_id` / `user_id`, distinct `session_id` suffix per agent name).

### Is it required?

**No.** Both `AgentRunner` and `AgentOrchestrator` default to an empty `RunContext()` if you omit it:

```python
runner = AgentRunner(config=config, tool_registry=registry)  # valid
```

Use an explicit `RunContext` when you have **multi-tenancy**, **per-user sessions**, or **tools that need request-scoped data** (DB handle, API client, plan flags). For a local script with one user and in-memory storage, you can skip it and pass `session_id=` only on `run()`.

### Why the minimal example still shows `RunContext`

The single-agent snippet includes `RunContext(tenant_id="demo", session_id="sess-1")` to mirror production (SaaS API) and to show the usual pattern: **config = what the agent is; run context = who is calling right now**. For a quick local test you can remove it:

```python
runner = AgentRunner(config=config, tool_registry=registry)
result = await runner.run(user_message="Echo hello", session_id="sess-1")
```

| | `AgentConfig` | `RunContext` |
|---|---------------|--------------|
| Lifetime | Built once (or per tenant template) | New per HTTP request / job |
| Holds | LLM, persona, tools, limits | tenant_id, user_id, session_id, metadata |
| Defines the agent? | Yes | No — defines the **call** |

---

## Tool registry: what it is, and standalone `@tool` functions

The LLM never calls Python functions directly. Nexus needs a **`ToolRegistry`**: a catalog of callables with JSON schemas that get sent to the model, then executed when the model requests a tool.

```
  @tool on a function/method
           │
           ▼
  registry.register_tool(fn)     or     registry.register_plugin(MyPlugin())
           │
           ▼
  AgentRunner asks registry for schemas → LLM picks a tool → registry.execute(...)
```

`AgentRunner` **requires** a `tool_registry` argument. There is no “pass a list of raw functions into the runner” API — you decorate, then register.

### Can I use plain functions?

**Yes**, as long as they use the `@tool` decorator and you register them:

```python
from nexus.tools.decorators import tool

@tool(name="echo", description="Echo text back")
def echo(text: str) -> str:
    return text

registry = ToolRegistry()
registry.register_tool(echo)  # stored as "global.echo" by default
```

Standalone functions live under the **`global`** plugin namespace unless you pass `plugin_name=`:

```python
registry.register_tool(echo, plugin_name="utilities")  # → "utilities.echo"
```

### When to use `register_plugin` (`@tool_plugin`)

Use a **plugin class** when you have several related tools, shared state, or a clear namespace (matches `AgentConfig.tool_plugins`):

```python
@tool_plugin(name="web_search")
class WebSearchPlugin:
    @tool(name="search")
    def search(self, query: str) -> str:
        return f"Results for {query}"
```

```python
registry.register_plugin(WebSearchPlugin())
# LLM sees tool name: web_search.search
```

| Approach | Register with | LLM tool name | Good for |
|----------|---------------|---------------|----------|
| One-off function | `register_tool(fn)` | `global.echo` (default) | Scripts, 1–2 tools |
| Plugin class | `register_plugin(instance)` | `web_search.search` | SaaS tool packs, grouping, `tool_plugins` gating |

### `AgentConfig.tool_plugins` — allow-list, not registration

- **Registry** = everything your app *could* expose.
- **`tool_plugins`** = which plugin namespaces *this agent* may see (filtered in `get_tool_schemas_for_llm`).

```python
AgentConfig(
    name="researcher",
    tool_plugins=["web_search"],  # only web_search.* tools go to the LLM
    ...
)
```

| `tool_plugins` value | Effect |
|--------------------|--------|
| `[]` (default) | No filter — all registered tools are eligible |
| `["web_search", "database"]` | Only tools from those plugin namespaces |

The SaaS example registers all plugins once (`SHARED_TOOL_REGISTRY`) and each agent config allow-lists via plan (`allowed_tool_plugins`).

### One registry, many agents

Typical pattern: build **one** `ToolRegistry` at app startup, pass the **same instance** into every `AgentRunner` / `AgentOrchestrator`. Per-agent differences come from `tool_plugins` on each `AgentConfig`, not from separate registries.

```python
SHARED = ToolRegistry()
SHARED.register_plugin(WebSearchPlugin())
SHARED.register_plugin(DatabasePlugin())

runner_a = AgentRunner(config=cfg_a, tool_registry=SHARED)  # cfg_a.tool_plugins = ["web_search"]
runner_b = AgentRunner(config=cfg_b, tool_registry=SHARED)  # cfg_b.tool_plugins = ["database"]
```

---

## Shared context: groups, multiple agents, and what is *not* shared

“Context” means different things in Nexus. Defaults differ for each.

### 1. `RunContext` (request / tenant scope)

| Behavior | Default |
|----------|---------|
| Group → members | **Same** `tenant_id` and `user_id` copied from the orchestrator’s `RunContext` |
| Per-member `session_id` | **Different** — orchestrator sets `{group_session_id}_{member.name}` (e.g. `sess-1_researcher`, `sess-1_analyst`) |

You **pass** one `RunContext` into `AgentOrchestrator`; you do not need one per member. Members do not share one session id unless you customize orchestration.

### 2. Tool registry

**Not automatic** — you pass the same `ToolRegistry` instance if you want shared tools (recommended). Each agent still filters via its own `tool_plugins`.

### 3. Session / conversation history (LLM memory)

**Not shared by default.** Each agent has its **own** persisted session (separate turn history, tool results, RCS summaries). Agent A’s prior turns are **not** injected into Agent B’s context window automatically.

**Pipeline pattern** (default handoff): member N+1 receives member N’s **`final_response` string** as its `user_message` — that is the built-in shared *workflow* context, not full chat logs:

```
User message ──► Researcher (own session) ──► final text ──► Analyst (own session) ──► ...
```

So for groups: **shared outcome text in pipeline; separate session stores per agent.**

### 4. `initial_context` on `run()` (optional session metadata)

```python
await runner.run(
    user_message="Hello",
    session_id="sess-1",
    initial_context={"deal_id": "D-99"},  # merged into session.metadata once
)
```

This is **per runner / per session**, not propagated across group members. To pass structured state through a pipeline, either embed it in the handoff message or put it in `RunContext.metadata` (visible to all tools on that request).

### Summary table

| Kind of context | Shared across group by default? | How to share intentionally |
|-----------------|----------------------------------|----------------------------|
| `RunContext.tenant_id` / `user_id` | Yes (from parent orchestrator) | Pass one `RunContext` into `AgentOrchestrator` |
| `RunContext.metadata` | Yes (same values on member contexts) | Set on group `RunContext` before `run()` |
| Tool registry | No (you choose) | Pass same `ToolRegistry` instance |
| Session / turn history | No | Pipeline handoff text; or custom orchestration / same `session_id` if you control runners yourself |
| LLM provider config | No | Each `AgentConfig.llm` is independent |

There is **no** single global “group session” object that merges all agents’ transcripts today. If you need one shared chat thread for every agent, use one `AgentRunner` or extend the orchestrator to reuse one `session_id` for all members (not the current default).

---

## Run the bundled SaaS API example

From the repo root:

```bash
uv run uvicorn examples.nexus_saas_api:app --host 0.0.0.0 --port 8000
```

Single agent:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: pro_tenant_1" \
  -d '{"message": "Search for Nexus framework releases"}'
```

Multi-agent (PRO/ENTERPRISE tenants only):

```bash
curl -X POST http://localhost:8000/v1/multi-agent/run \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: pro_tenant_1" \
  -d '{"message": "Research and analyze our churn"}'
```

That example’s flow matches the diagram above: resolve tenant → **build `AgentConfig`** → **`AgentRunner` / `AgentOrchestrator`** → return JSON.

---

## What goes on `AgentConfig` (quick reference)

| Field | Purpose |
|-------|---------|
| `name` | Agent id (sessions, logging) |
| `llm` | **Provider + model + key** for this agent only |
| `persona` | `role` / `goal` system framing |
| `turns` | `max_turns`, `max_tool_calls_per_turn` |
| `tool_plugins` | Allow-list of plugin namespaces (see Tool registry section) |
| `storage` | Where conversation sessions live |
| `memory` | Entity / vector / working memory toggles |
| `rcs` | Long-context summarization (optional) |

---

## Next reads

- [saas_integration_guide.md](saas_integration_guide.md) — tenants, plans, storage isolation
- [nexus_framework_walkthrough.md](nexus_framework_walkthrough.md) — LiteLLM routing and SQLite storage
- [NEXUS_AGENT_PRD.md](NEXUS_AGENT_PRD.md) — full product/design spec
