# Tools

**Who this is for:** Developers exposing Python functions so the LLM can call them.

## Key terms

- **Tool** — A Python function the LLM can request to run.
- **Tool registry** — `ToolRegistry`; catalog of tools with JSON schemas sent to the model.
- **Plugin** — A class grouping related tools under one namespace.
- **Allow-list** — `tool_plugins` on `AgentConfig`; which plugin namespaces this agent may use.

## Why you need a registry

The LLM cannot call your Python code directly. Nexus:

1. Sends tool schemas to the model
2. Runs the matching function when the model asks
3. Returns the result to the model

`AgentRunner` **requires** a `tool_registry` argument.

## Standalone @tool functions

```python
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

@tool(name="echo", description="Echo text back")
def echo(text: str) -> str:
    return text

registry = ToolRegistry()
registry.register_tool(echo)  # → global.echo
```

| @tool parameter | Required? | Default | What it does |
|----------------|-----------|---------|--------------|
| `name` | No | function name | Tool name the LLM sees |
| `description` | No | docstring | Human-readable description |
| `timeout_seconds` | No | `30` | Max seconds for tool execution |
| `requires_approval` | No | `False` | **Planned** human-in-the-loop gate — not enforced in runner yet; use external HITL ([runtime-control.md](../guides/runtime-control.md)) |

`register_tool(fn, plugin_name="utilities")` → `utilities.echo`.

## @tool_plugin classes

```python
from nexus.tools.decorators import tool, tool_plugin

@tool_plugin(name="web_search")
class WebSearchPlugin:
    @tool(name="search")
    def search(self, query: str) -> str:
        return f"Results for {query}"

registry.register_plugin(WebSearchPlugin())  # → web_search.search
```

## RunContext injection

Tools often need request-scoped data (tenant id, user id, plan tier) that the LLM should not choose. Declare a `RunContext` parameter on the tool function — Nexus strips it from the schema sent to the model and injects it at execution time from `run_context=` on `AgentRunner`, `AgentOrchestrator`, or `OrchestrationRuntime`.

```python
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin

@tool_plugin(name="lookup")
class LookupPlugin:
    @tool(name="lookup_account", description="Look up a customer account by id.")
    def lookup_account(self, account_id: str, ctx: RunContext) -> str:
        plan = ctx.get("plan_tier", "free")
        return f"[tenant={ctx.tenant_id}, plan={plan}] Account {account_id}: active"
```

| Parameter kind | Who sets it | Visible to LLM? |
|----------------|-------------|-----------------|
| Typed tool args (e.g. `account_id: str`) | LLM in the tool call | Yes |
| `RunContext` (any param name) | Your app via `run_context=` | No |

The parameter can be named `ctx`, `context`, or anything else — only the type `RunContext` matters. Read extra per-request values from `ctx.metadata` with `ctx.get("key")`. Full field list: [run-context.md](run-context.md).

## tool_plugins allow-list

| Value | Effect |
|-------|--------|
| `[]` (default) | All registered tools eligible |
| `["web_search"]` | Only `web_search.*` tools sent to LLM |

Registry = everything your app *could* expose. `tool_plugins` = what *this agent* may see.

## One registry, many agents

Build one `ToolRegistry` at app startup. Pass the same instance to every runner. Per-agent differences come from `tool_plugins` on each `AgentConfig`.

## YAML orchestration plugins

```yaml
plugins:
  web_search: examples.nexus_saas_api.WebSearchPlugin
```

Import path format: `module.path.ClassName`. Class is instantiated; its tools are registered.

You can also pass a pre-built `ToolRegistry` to `OrchestrationRuntime.from_manifest()`.

## Next steps

- [Getting started (Python)](../getting-started-python.md)
- [Skills](skills.md) — different from custom tools; uses agentskills.io folders
