"""Expose Nexus toolsets as an MCP server."""

from __future__ import annotations

import json
from typing import Any

from nexus.tools.registry import ToolRegistry


def toolset_to_mcp_tools(registry: ToolRegistry, tool_names: list[str]) -> list[dict[str, Any]]:
    """Convert registry tools to MCP tool descriptors."""
    schemas = registry.schemas_for(tool_names)
    out: list[dict[str, Any]] = []
    for schema in schemas:
        out.append(
            {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "inputSchema": schema.get("parameters", {"type": "object"}),
            }
        )
    return out


async def execute_mcp_tool_call(
    registry: ToolRegistry,
    name: str,
    arguments: dict[str, Any],
    ctx: Any,
) -> str:
    """Execute a tool by MCP name."""
    result = await registry.execute_tool(name, arguments, ctx)
    if isinstance(result, str):
        return result
    return json.dumps(result, default=str)
