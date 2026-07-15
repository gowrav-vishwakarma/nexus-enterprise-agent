# Tools

**Who this is for:** Developers exposing Python functions so the LLM can call them.

## Key terms

- **Tool** — A Python function the LLM can request to run.
- **Tool registry** — `ToolRegistry`; catalog of tools with JSON schemas sent to the model.
- **Plugin** — A class grouping related tools under one namespace.
- **Allow-list** — `tool_plugins` on `AgentConfig`; which plugin namespaces this agent may use.
- **Toolset** — A named pack of tools (and nested packs) the client can enable per request.
- **Client tool** — A tool with `execution="client"`; the run pauses until your UI returns a result via `resume()`.

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
registry.register_tool(echo, plugin_name="")  # → echo (bare / flat name)
```

| @tool parameter | Required? | Default | What it does |
|----------------|-----------|---------|--------------|
| `name` | No | function name | Tool name the LLM sees |
| `description` | No | docstring | Human-readable description |
| `tags` | No | `[]` | Optional tags for metadata and filtering |
| `timeout_seconds` | No | `30` | Max seconds for tool execution |
| `requires_approval` | No | `False` | **Planned** human-in-the-loop gate — not enforced in runner yet; use external HITL ([runtime-control.md](../guides/runtime-control.md)) |
| `execution` | No | `"server"` | `"server"` runs in-process; `"client"` pauses the run and waits for `AgentRunner.resume()` |

`register_tool(fn, plugin_name="utilities")` → `utilities.echo`.

Pass `plugin_name=""` or `None` to register a **flat** tool name (no `plugin.` prefix). Useful when a product already exposes bare names such as `execute_sql` or `memory_write`. `execute()` already resolves no-dot names via its fallback when the caller passes the bare name as `plugin` with an empty `tool`.

### Client tools (`execution="client"`)

Use client tools when the browser or mobile app must run the tool (pick a file, show a form, call a device API):

```python
@tool(name="pick_file", execution="client", description="Ask the user to pick a file")
def pick_file(prompt: str) -> str:
    """Schema-only stub; the real work happens in the client."""
    return ""
```

When the model calls a client tool:

1. The runner appends a `PendingInteraction` and sets status `paused`
2. Streaming emits `client_tool_call` (or `elicitation` for `*.request_user_input`) then `paused`
3. Your app runs the tool and calls `resume(session_id, results=[...])`

Details: [runtime-control.md](../guides/runtime-control.md#pause-and-resume-client-tools).

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

The parameter can be named `ctx`, `context`, or anything else. Nexus detects:

- Plain `RunContext`
- `Optional[RunContext]` / `RunContext | None` (common when tools also accept `**kwargs`)
- Parameters literally named `ctx` or `run_context` (even without a resolved annotation)

`*args` / `**kwargs` are never included in the LLM schema. Read extra per-request values from `ctx.metadata` with `ctx.get("key")`. Full field list: [run-context.md](run-context.md).

## tool_plugins allow-list

| Value | Effect |
|-------|--------|
| `[]` (default) | All registered tools eligible |
| `["web_search"]` | Only `web_search.*` tools sent to LLM |

Registry = everything your app *could* expose. `tool_plugins` = what *this agent* may see.

## Toolsets

A **toolset** is a named pack of fully-qualified tool names (and optional nested packs). Use toolsets when a product UI lets users toggle capability packs per chat.

### Toolset fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Pack id (also the dict key on `AgentConfig.toolsets`) |
| `description` | No | `""` | Shown in UI catalogs |
| `visibility` | No | `"hidden"` | `"hidden"` or `"frontend"` (only frontend packs appear in the catalog) |
| `default_enabled` | No | `False` | Hint for UIs; does not auto-enable by itself |
| `includes` | No | `[]` | Other toolset names to pull in recursively |
| `tools` | No | `[]` | Fully-qualified tool names, e.g. `memory.write` |

### AgentConfig toolset fields

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `toolsets` | No | `{}` | Map of name → `Toolset` definitions |
| `base_toolsets` | No | `[]` | Always-on toolset names for this agent |
| `optional_toolsets` | No | `[]` | Packs the client may enable per request |

### Enabling packs on a run

Pass `enabled_toolsets` to `run()` / `run_stream()`. Only names listed in `optional_toolsets` (or defined in `toolsets`) are accepted:

```python
result = await runner.run(
    "Summarize this PDF",
    session_id="chat-1",
    enabled_toolsets=["attachments", "web"],
)
```

Effective tools = expand(`base_toolsets` + `enabled_toolsets`).

When an agent defines `toolsets` or `base_toolsets`, the runner uses those packs as the **allow-list** for which tools reach the model. It does **not** also apply the `tool_plugins` namespace filter on that pass. That matters for **flat** tools registered with `plugin_name=""`: they are not in any plugin namespace, so a combined `tool_plugins` + toolsets filter could drop them incorrectly. Configure toolsets (and `enabled_toolsets` on each run) instead of relying on `tool_plugins` alone when you use flat names.


### Frontend catalog

```python
from nexus.tools.toolsets import list_frontend_toolsets

catalog = list_frontend_toolsets(
    agent_config.toolsets,
    tool_descriptions={"memory.write": "Save a fact"},
)
# → ToolsetCatalog entries with visibility=frontend only
```

Expose this from your `/tools` or settings API so the UI can show toggleable packs.

## One registry, many agents

Build one `ToolRegistry` at app startup. Pass the same instance to every runner. Per-agent differences come from `tool_plugins` and toolsets on each `AgentConfig`.

## YAML orchestration plugins

```yaml
plugins:
  web_search: examples.nexus_saas_api.WebSearchPlugin
```

Import path format: `module.path.ClassName`. Class is instantiated; its tools are registered.

You can also pass a pre-built `ToolRegistry` to `OrchestrationRuntime.from_manifest()`.

## Next steps

- [Getting started (Python)](../getting-started-python.md)
- [Runtime control](../guides/runtime-control.md) — pause/resume for client tools
- [Skills](skills.md) — different from custom tools; uses agentskills.io folders
- [Agent runner](agent-runner.md) — `enabled_toolsets` and `resume()`
