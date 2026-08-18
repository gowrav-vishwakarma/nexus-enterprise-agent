# MCP integration (`nexus[mcp]`)

**MCP** (Model Context Protocol) is a standard way for agents to call tools hosted
by a separate process or service. Nexus supports both directions, but they are at
very different levels of maturity — read the status note on each before relying on it.

## Server mode — ready to use

Expose tools you already registered in a `ToolRegistry` so other agents (Cursor,
Claude Desktop, another Nexus app) can call them. You supply the transport; Nexus
converts schemas and dispatches calls.

```python
from nexus.mcp.server import execute_mcp_tool_call, toolset_to_mcp_tools

descriptors = toolset_to_mcp_tools(registry, ["get_invoice", "search_products"])
# → [{"name": ..., "description": ..., "inputSchema": {...}}, ...]

result = await execute_mcp_tool_call(registry, "get_invoice", {"id": "INV-1"}, ctx)
```

Because dispatch goes through `registry.execute_tool(..., ctx)`, every call carries a
`RunContext`, so tenant scoping and tool policy apply exactly as they do in a normal
agent run.

## Client mode — scaffold only

> **Status: not functional yet.** `MCPClient.connect()` discovers no tools and
> `call_tool()` returns a placeholder response. The transport (stdio and HTTP) is
> not implemented. The types below exist so you can wire your own transport in, and
> so the manifest and registry integration is settled — do not point a product at
> this expecting real MCP servers to work.

```python
from nexus.mcp import MCPServerConfig, mount_mcp_tools

servers = [
    MCPServerConfig(
        name="filesystem",
        command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        transport="stdio",          # stdio | sse | streamable-http
        tools=["read_file", "list_dir"],  # optional allow-list; omit = all discovered tools
    )
]
mounted = await mount_mcp_tools(registry, servers)   # currently returns []
```

Once a transport is implemented, each discovered tool mounts as `{prefix}.{tool}`
where `prefix` is `MCPServerConfig.tool_prefix` or the server name.

### Per-tenant credentials

Pass `credential_resolver` so each tenant uses its own credentials instead of a
global config file:

```python
def resolve(ctx, server_name):
    return {"api_key": ctx.services["vault"].get(ctx.tenant_id, server_name)}

await mount_mcp_tools(registry, servers, credential_resolver=resolve)
```

The resolver receives the calling `RunContext` and the server name, and its return
value is merged into the tool arguments. Credentials should come from
`RunContext.auth` or `RunContext.services`, never module-level config.

### Client checklist (roadmap M2)

When the transport is implemented, a working client must include:

| Field / hook | Why |
|--------------|-----|
| `MCPServerConfig.transport` | Explicit `stdio`, `sse`, or `streamable-http` (do not guess) |
| `MCPServerConfig.tools` | Allow-list; `None` mounts every discovered tool |
| `credential_resolver(ctx, server_name)` | Per-tenant secrets from `RunContext`, not a global file |

`mount_mcp_tools` already skips tools that are not in `server.tools` when that list is set.

## Next steps

- [Tools](tools.md)
- [Run context](run-context.md)
- [Guardrails](guardrails.md)
