"""Dummy tools for the voice_grpc example.

Shows how to expose flat Python functions to a voice agent via a toolset.
The voice_lab bootstrap registers these tools under the ``voice_tools``
toolset, and the manifest selects that pack with ``agent.toolset: voice_tools``.

These are intentionally trivial (date/time) so the example runs anywhere with
no external services.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


@tool(
    name="get_current_datetime",
    description=(
        "Return the current date and time. Optionally pass an IANA timezone "
        "like 'Asia/Kolkata' or 'UTC'; defaults to the server's local time."
    ),
)
def get_current_datetime(timezone: str = "") -> str:
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


def register_voice_tools(registry: ToolRegistry) -> ToolRegistry:
    """Register the voice demo tools as a single toolset."""
    registry.add_toolset(
        "voice_tools",
        [get_current_datetime],
        description="Voice assistant helper tools",
    )
    return registry
