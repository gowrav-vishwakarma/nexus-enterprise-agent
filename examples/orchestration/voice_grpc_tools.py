"""Dummy tools for the voice_grpc example.

Shows how to expose Python functions to a voice agent. The manifest registers
this plugin under ``plugins:`` and the agent opts in via ``agent.tool_plugins``.
These are intentionally trivial (date/time) so the example runs anywhere with
no external services.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nexus.tools.decorators import tool, tool_plugin


@tool_plugin(name="voice_tools")
class VoiceToolsPlugin:
    """Small helper tools a voice assistant can call mid-conversation."""

    @tool(
        name="get_current_datetime",
        description=(
            "Return the current date and time. Optionally pass an IANA timezone "
            "like 'Asia/Kolkata' or 'UTC'; defaults to the server's local time."
        ),
    )
    def get_current_datetime(self, timezone: str = "") -> str:
        """Return a human-readable current date and time."""
        tz = None
        if timezone:
            try:
                tz = ZoneInfo(timezone)
            except (ZoneInfoNotFoundError, ValueError):
                return f"Unknown timezone {timezone!r}. Try 'Asia/Kolkata' or 'UTC'."
        now = datetime.now(tz)
        label = timezone or "server local time"
        return now.strftime(f"%A, %d %B %Y, %I:%M %p ({label})")
