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
| `requires_approval` | No | `False` | Future human-in-the-loop gate |

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
