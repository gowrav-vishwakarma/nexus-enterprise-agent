"""Tool policy engine for allow/deny and plan-tier gating."""

from __future__ import annotations

from typing import Optional

from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry


class ToolPolicyEngine:
    """Resolve effective tool allow/deny lists from RunContext."""

    def __init__(
        self,
        *,
        deny: Optional[set[str]] = None,
        allow: Optional[set[str]] = None,
    ):
        self.deny = deny or set()
        self.allow = allow

    @classmethod
    def from_context(cls, ctx: RunContext) -> "ToolPolicyEngine":
        auth = ctx.auth or {}
        deny = set(auth.get("deny_tools") or [])
        allow_raw = auth.get("allow_tools")
        allow = set(allow_raw) if allow_raw else None
        return cls(deny=deny, allow=allow)

    def is_allowed(self, tool_name: str, registry: ToolRegistry) -> bool:
        try:
            resolved = registry.resolve_tool_name(tool_name)
        except ValueError:
            resolved = tool_name
        if resolved in self.deny:
            return False
        if self.allow is not None and resolved not in self.allow:
            return False
        return True
