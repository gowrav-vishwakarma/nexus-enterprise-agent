"""Toolset packs — base + optional bundles with recursive includes."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Toolset(BaseModel):
    """A named bundle of tools and/or nested toolsets."""

    name: str
    description: str = ""
    visibility: Literal["hidden", "frontend"] = "hidden"
    default_enabled: bool = False
    includes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(
        default_factory=list,
        description="Fully-qualified tool names, e.g. memory.write",
    )


class ToolsetCatalog(BaseModel):
    """Resolved catalog entry for product /tools endpoints."""

    toolset: str
    description: str
    default: bool
    visibility: str
    tools: list[dict[str, str]]


def resolve_toolset_tools(
    name: str,
    toolsets: dict[str, Toolset],
    *,
    _seen: Optional[set[str]] = None,
) -> set[str]:
    """Expand a toolset name into concrete tool names (recursive includes)."""
    seen = _seen if _seen is not None else set()
    if name in seen:
        return set()
    seen.add(name)
    ts = toolsets.get(name)
    if ts is None:
        return {name} if "." in name else set()
    out = set(ts.tools)
    for child in ts.includes:
        out |= resolve_toolset_tools(child, toolsets, _seen=seen)
    return out


def effective_tools(
    *,
    base_toolsets: list[str],
    enabled_toolsets: Optional[list[str]],
    optional_toolsets: list[str],
    toolsets: dict[str, Toolset],
    channel_override: Optional[list[str]] = None,
) -> set[str]:
    """Resolve the concrete tool name set for one request."""
    if channel_override is not None:
        names = channel_override
    else:
        names = list(base_toolsets)
        for name in enabled_toolsets or []:
            if name in optional_toolsets or name in toolsets:
                names.append(name)
    tools: set[str] = set()
    for name in names:
        tools |= resolve_toolset_tools(name, toolsets)
    return tools


def list_frontend_toolsets(
    toolsets: dict[str, Toolset],
    *,
    tool_descriptions: Optional[dict[str, str]] = None,
) -> list[ToolsetCatalog]:
    """Build the catalog shown to UIs (visibility=frontend only)."""
    tool_descriptions = tool_descriptions or {}
    out: list[ToolsetCatalog] = []
    for ts in toolsets.values():
        if ts.visibility != "frontend":
            continue
        expanded = sorted(resolve_toolset_tools(ts.name, toolsets))
        out.append(
            ToolsetCatalog(
                toolset=ts.name,
                description=ts.description,
                default=ts.default_enabled,
                visibility=ts.visibility,
                tools=[
                    {"name": t, "description": tool_descriptions.get(t, "")}
                    for t in expanded
                ],
            )
        )
    return out


def filter_schemas_by_tools(
    schemas: list[dict[str, Any]], allowed: Optional[set[str]]
) -> list[dict[str, Any]]:
    """Keep only schemas whose name is in ``allowed``. None = keep all."""
    if allowed is None:
        return schemas
    return [s for s in schemas if s.get("name") in allowed]
