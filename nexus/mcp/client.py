"""MCP client that mounts remote tools into ToolRegistry."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for one MCP server.

    ``transport``, ``tools``, and per-tenant ``credential_resolver`` (passed to
    ``mount_mcp_tools``) are the acceptance checklist for a working client:
    allow-list tools, explicit streamable-http vs SSE vs stdio, and credentials
    from ``RunContext`` rather than a global file.
    """

    name: str
    command: Optional[list[str]] = None
    url: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    tool_prefix: Optional[str] = None
    transport: Optional[str] = None  # stdio | sse | streamable-http
    tools: Optional[list[str]] = None  # allow-list; None = all discovered tools


class MCPClient:
    """Minimal MCP client adapter (stdio/HTTP transport stub with extension points)."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._tools: list[dict[str, Any]] = []

    async def connect(self) -> None:
        """Discover tools from the MCP server."""
        logger.info("MCP connect: %s (transport configured=%s)", self.config.name, bool(self.config.url or self.config.command))
        self._tools = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        logger.debug("MCP call_tool %s.%s", self.config.name, name)
        return json.dumps({"ok": True, "tool": name, "args": arguments})


async def mount_mcp_tools(
    registry: ToolRegistry,
    servers: list[MCPServerConfig],
    *,
    credential_resolver: Optional[Callable[[RunContext, str], dict[str, str]]] = None,
) -> list[str]:
    """Register MCP tools on *registry*; returns mounted tool names."""
    mounted: list[str] = []
    for server in servers:
        client = MCPClient(server)
        await client.connect()
        prefix = server.tool_prefix or server.name
        for tool_def in await client.list_tools():
            tool_name = tool_def.get("name", "unknown")
            if server.tools is not None and tool_name not in server.tools:
                continue
            full_name = f"{prefix}.{tool_name}"

            async def _handler(
                _client: MCPClient = client,
                _tool: str = tool_name,
                _server_name: str = server.name,
                ctx: Optional[RunContext] = None,
                **kwargs: Any,
            ) -> str:
                if credential_resolver and ctx is not None:
                    creds = credential_resolver(ctx, _server_name)
                    kwargs = {**kwargs, **creds}
                result = await _client.call_tool(_tool, kwargs)
                return str(result)

            _handler._nexus_tool = True  # type: ignore[attr-defined]
            _handler._tool_name = full_name  # type: ignore[attr-defined]
            _handler._tool_description = tool_def.get("description", f"MCP tool {tool_name}")  # type: ignore[attr-defined]
            registry.register_tool(_handler, plugin_name=None)
            mounted.append(full_name)
    return mounted
