# Getting started with the Python API

**Who this is for:** Developers who want to build agent config in code without YAML files.

## Key terms

- **Agent config** — A Python object (`AgentConfig`) that describes one agent.
- **Tool registry** — A catalog (`ToolRegistry`) of tools the LLM can call.
- **Runner** — `AgentRunner` executes the agent loop when you call `run()`.
- **Run context** — `RunContext` carries customer id, user id, and chat thread id.

## The flow in four steps

1. Build `AgentConfig` (model, personality, limits).
2. Build `ToolRegistry` and register tools.
3. Create `AgentRunner` with config, registry, storage, and run context.
4. Call `await runner.run(user_message=...)`.

## Minimal example

```python
import asyncio
from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(name="echo")
def echo(text: str) -> str:
    return text


async def main():
    config = AgentConfig(
        name="assistant",
        llm=LLMProviderConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key=SecretStr("sk-..."),
        ),
        persona=AgentPersonaConfig(
            role="Helpful assistant",
            goal="Answer clearly.",
        ),
    )

    registry = ToolRegistry()
    registry.register_tool(echo)

    runner = AgentRunner(
        config=config,
        tool_registry=registry,
        run_context=RunContext(tenant_id="demo", user_id="user-1", session_id="sess-1"),
    )

    result = await runner.run(user_message="Echo hello")
    print(result.final_response)


asyncio.run(main())
```

## Complete annotated example

Every `AgentConfig`, `LLMProviderConfig`, `AgentRunner`, and `run()` parameter with defaults:

[assets/complete-agent.annotated.py](assets/complete-agent.annotated.py)

## What goes where

| Setting | Object |
|---------|--------|
| Model, persona, turn limits, memory, tools allowed | `AgentConfig` |
| Customer, user, chat thread id | `RunContext` |
| Where chat history is saved | `storage_config` on `AgentRunner` |
| Tools the LLM can call | `ToolRegistry` (required) |

Full diagram: [architecture.md](architecture.md).

## Tools

The LLM cannot call your Python functions directly. You must:

1. Decorate a function with `@tool`
2. Register it on a `ToolRegistry`
3. Pass that registry to `AgentRunner`

```python
registry.register_tool(echo)           # → global.echo
registry.register_tool(echo, plugin_name="util")  # → util.echo
```

Use `tool_plugins=["web_search"]` on `AgentConfig` to allow-list plugin namespaces. Empty list `[]` means all registered tools are eligible.

Details: [reference/tools.md](reference/tools.md).

## Storage

Pass `storage_config` on the runner (preferred in production):

```python
from nexus.config.storage import SessionStorageConfig

runner = AgentRunner(
    config=config,
    tool_registry=registry,
    storage_config=SessionStorageConfig(
        adapter="sqlite",
        adapter_config={"tenant_scoped": True},
    ),
)
```

Default without `storage_config`: in-memory only (chat history lost when the process exits).

Details: [reference/storage.md](reference/storage.md).

## Multi-agent teams (Python)

Build one `AgentConfig` per member, wrap them in `AgentGroupConfig`, and use `AgentOrchestrator`:

```python
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.config.agent import AgentGroupConfig

group = AgentGroupConfig(
    name="pipeline",
    pattern="pipeline",
    members=[researcher_cfg, analyst_cfg],
)

orchestrator = AgentOrchestrator(
    config=group,
    tool_registry=registry,
    storage_config=storage_config,
    run_context=RunContext(session_id="group-1"),  # set before init
)
result = await orchestrator.run("Analyze Q4 revenue")
```

Details: [reference/multi-agent.md](reference/multi-agent.md).

Or use YAML orchestration instead: [getting-started.md](getting-started.md).

## When to use Python vs YAML

| Use Python API when | Use YAML orchestration when |
|--------------------|----------------------------|
| Config changes per tenant or subscription plan | Agent definitions are stable files |
| You already have a config factory in your app | Ops team owns agent YAML |
| You need types and IDE autocomplete on config | You want `${ENV:...}` in config files |

## Next steps

- [Agent config reference](reference/agent-config.md)
- [Runner reference](reference/agent-runner.md)
- [Memory](reference/memory.md)
- [SaaS example](guides/saas-example.md)
