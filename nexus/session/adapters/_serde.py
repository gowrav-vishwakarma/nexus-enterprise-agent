"""Shared JSON serialization for session storage adapters."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Union

from nexus.session.models import AgentSession


def _parse_datetimes(parsed: dict[str, Any]) -> None:
    for key in ("created_at", "updated_at"):
        if parsed.get(key) and isinstance(parsed[key], str):
            parsed[key] = datetime.fromisoformat(parsed[key])
    for turn in parsed.get("turns", []):
        if turn.get("timestamp") and isinstance(turn["timestamp"], str):
            turn["timestamp"] = datetime.fromisoformat(turn["timestamp"])
        for tc in turn.get("tool_calls", []):
            if tc.get("timestamp") and isinstance(tc["timestamp"], str):
                tc["timestamp"] = datetime.fromisoformat(tc["timestamp"])


def session_to_json(session: AgentSession, *, pretty: bool = False) -> str:
    """Serialize an AgentSession to JSON."""
    indent = 2 if pretty else None
    return json.dumps(session.model_dump(), indent=indent, default=str)


def session_from_json(data: Union[str, dict[str, Any]]) -> AgentSession:
    """Deserialize JSON into an AgentSession with datetime fields restored."""
    parsed = json.loads(data) if isinstance(data, str) else dict(data)
    _parse_datetimes(parsed)
    return AgentSession(**parsed)
