# Tools

**Who this is for:** Developers exposing Python functions so the LLM can call them.

## Key terms

- **Tool** — A Python function the LLM can request to run.
- **Tool registry** — `ToolRegistry`; catalog of tools with JSON schemas sent to the model.
- **Toolset** — A named pack of tools (and nested packs) defined on the registry; selected per agent via `AgentConfig.toolset`.
- **Plugin** — A class grouping related tools under one namespace (legacy path).
- **Allow-list** — `AgentConfig.toolset` (modern) or `tool_plugins` (legacy plugin namespace filter).
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
registry.add_tool(echo)  # → echo (flat name, no plugin prefix)
```

| @tool parameter | Required? | Default | What it does |
|----------------|-----------|---------|--------------|
| `name` | No | function name | Tool name the LLM sees |
| `description` | No | docstring | Human-readable description |
| `tags` | No | `[]` | Optional tags for metadata and filtering |
| `timeout_seconds` | No | `30` | Max seconds for tool execution |
| `requires_approval` | No | `False` | **Planned** human-in-the-loop gate — not enforced in runner yet; use external HITL ([runtime-control.md](../guides/runtime-control.md)) |
| `execution` | No | `"server"` | `"server"` runs in-process; `"client"` pauses the run and waits for `AgentRunner.resume()` |

`registry.add_tool(fn)` is the preferred modern API: it registers a flat tool name with no `plugin.` prefix. This matches products that already expose bare names such as `execute_sql` or `memory_write`. The legacy `register_tool(fn, plugin_name="utilities")` still registers `utilities.echo` if you need class-style namespaces, and `execute()` resolves bare, flat, and legacy namespaced names automatically.

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

## @tool_plugin classes (legacy)

Class-based plugins are still supported but are no longer the primary path. Prefer flat `@tool` functions + `add_toolset()` for new code.

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

## Toolsets

A **toolset** is a named pack of tools (and optional nested packs) defined on the `ToolRegistry`. Use toolsets when a product UI lets users toggle capability packs per chat, or when you want a flat-name tool allow-list.

## tool_plugins allow-list (legacy)

`tool_plugins` is the legacy namespace filter for class-based plugins.

| Value | Effect |
|-------|--------|
| `[]` (default) | All registered tools eligible |
| `["web_search"]` | Only `web_search.*` tools sent to LLM |

Registry = everything your app *could* expose. `tool_plugins` = what *this agent* may see. Prefer `AgentConfig.toolset` for new code; see below.

## Defining toolsets

Toolsets are **owned by the `ToolRegistry`**. You define them on the same registry that holds the tools, so every referenced tool is validated at define time. An agent then points at a toolset with a single `AgentConfig.toolset` field.

### Defining a toolset

```python
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry

@tool(name="memory_write", description="Save a fact")
def memory_write(fact: str) -> str:
    ...

registry = ToolRegistry()
# Pass @tool callables — each is registered with a flat name automatically.
registry.add_toolset("memory", [memory_write, memory_search])
registry.add_toolset(
    "chat_core",
    includes=["memory"],
)
```

You can still pass registered tool name strings to `define_toolset` / `add_toolset` when tools were added with `add_tool` or `register_tool` first. Define child toolsets before parents (`includes` must already exist).

`add_toolset` / `define_toolset` raises `ValueError` immediately if any tool name is not registered, or if an `includes` entry is not an already-defined toolset.

Use `registry.add_tool(fn)` to register a standalone @tool with a flat name. Use `await registry.execute_tool("memory_write", args, ctx)` to run by flat or legacy namespaced name.

### define_toolset / add_toolset arguments

| Name | Required? | Default | What it does |
|------|-----------|---------|--------------|
| `name` | Yes | — | Pack id |
| `tools` | No | `()` | Registered tool name strings **or** `@tool` callables (must be registered) |
| `includes` | No | `()` | Other toolset names to pull in recursively (must be defined first) |
| `description` | No | `""` | Shown in UI catalogs |
| `visibility` | No | `"hidden"` | `"hidden"` or `"frontend"` (only frontend packs appear in the catalog) |
| `default_enabled` | No | `False` | Hint for UIs; does not auto-enable by itself |

### Pointing an agent at a toolset

Set a single `AgentConfig.toolset` — a toolset name, a list of names, or `None`:

```python
config = AgentConfig(
    name="chat",
    llm=...,
    toolset="chat_core",              # one pack
    # toolset=["chat_core", "attachments"],  # or a computed list per request
    # toolset=None,                          # no restriction: all tools visible
)
```

At run time the runner calls `registry.resolve_toolset(config.toolset)` to build the tool allow-list. When `toolset` is `None` there is no restriction and every registered tool is visible. A per-run `run_context["toolset_override"]` (also a name or list) takes precedence over `config.toolset`.

When a toolset allow-list is active, the runner uses it as the **allow-list** for which tools reach the model. It does **not** also apply the `tool_plugins` namespace filter on that pass. That matters for **flat** tools registered with `plugin_name=""`: they are not in any plugin namespace, so a combined `tool_plugins` + toolset filter could drop them incorrectly. Use a `toolset` instead of relying on `tool_plugins` alone when you use flat names.

### Runtime tool granting

You can widen or narrow a live agent's allow-list between turns (schemas are re-filtered every turn, so no restart is needed):

```python
runner.grant_tools("tenant.new_tool")       # add explicit tool name(s)
runner.grant_toolset("attachments")          # union in a defined toolset
runner.revoke_tools(["tenant.old_tool"])     # remove tool name(s)
```

Brand-new tools registered on the shared registry at runtime (`registry.add_tool(...)`) become callable once granted — or immediately if the agent has no toolset restriction (`toolset=None`). When the agent is unrestricted, `grant_tools`/`grant_toolset` are no-ops because everything is already visible.

### Frontend catalog

```python
catalog = registry.list_frontend_toolsets(
    tool_descriptions={"memory.write": "Save a fact"},
)
# → ToolsetCatalog entries with visibility=frontend only
```

Expose this from your `/tools` or settings API so the UI can show toggleable packs.

## Package discovery

Scan a Python package for standalone `@tool` functions and register them in one call:

```python
from nexus.tools.registry import ToolRegistry

registry = ToolRegistry().discover_package(
    "myapp.tools",
    plugin_name="tenant",  # → tenant.execute_sql, tenant.memory_write, …
    skip={"helpers", "toolsets"},
)
```

| Argument | Effect |
|----------|--------|
| `plugin_name="tenant"` | Namespaced registration (`tenant.<tool_name>`) |
| `plugin_name=None` or `""` | Flat names (same as `register_tool(..., plugin_name="")`) |
| `skip` | Submodule basenames to skip (e.g. `registry_factory`, `toolsets`) |

Public registry helpers (prefer these over reading private `_tools`):

| Method | Purpose |
|--------|---------|
| `has(full_name)` | Whether a tool is registered |
| `tool_names()` | Sorted list of registered names |
| `get_tool(full_name)` | Callable + optional plugin instance |
| `count()` | Number of registered tools |
| `schemas_for(names)` | LLM schema dicts for a name list |
| `discover_package(...)` | Import submodules and register `@tool` functions |
| `define_toolset(...)` | Define a named toolset (validates tools/includes) |
| `has_toolset(name)` / `get_toolset(name)` | Look up a defined toolset |
| `list_toolsets()` | All defined toolsets |
| `list_frontend_toolsets(...)` | Catalog of `visibility="frontend"` packs |
| `resolve_toolset(name_or_names)` | Expand toolset name(s) → concrete tool name set (`None` → no restriction) |

Because `define_toolset` validates its tools and includes when called, a typo fails at import/build time — there is no separate boot-time validation step to run.

## One registry, many agents

Build one `ToolRegistry` at app startup. Define its toolsets, then pass the same instance to every runner. Per-agent differences come from the single `toolset` field on each `AgentConfig` (and the legacy `tool_plugins` namespace filter if you still use class-based plugins).

## YAML orchestration toolsets

The modern path is to build the registry in Python and pass it to `OrchestrationRuntime.from_manifest()`:

```python
registry = ToolRegistry()
registry.add_toolset("researcher", [web_search])
runtime = OrchestrationRuntime.from_manifest(manifest, run_context=ctx, tool_registry=registry)
```

```yaml
agents:
  researcher:
    toolset: researcher
```

The legacy `plugins:` block still works for class-based plugins:

```yaml
plugins:
  web_search: myapp.plugins.WebSearchPlugin
```

Import path format: `module.path.ClassName`. Class is instantiated; its tools are registered.

## Next steps

- [Getting started (Python)](../getting-started-python.md)
- [Runtime control](../guides/runtime-control.md) — pause/resume for client tools
- [Skills](skills.md) — different from custom tools; uses agentskills.io folders
- [Agent runner](agent-runner.md) — `toolset`, runtime grants, and `resume()`
