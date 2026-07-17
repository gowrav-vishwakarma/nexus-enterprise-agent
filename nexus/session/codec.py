"""Pluggable session JSON codec for storage adapters."""

from __future__ import annotations

import json
from datetime import datetime
from importlib import import_module
from typing import Any, Optional, Protocol, Union, runtime_checkable

from nexus.session.models import AgentSession


@runtime_checkable
class SessionCodec(Protocol):
    """Serialize / deserialize AgentSession for storage backends.

    Implement this to store a different JSON shape (legacy product blobs,
    slim UI DTOs, admin dialects) while the runner always uses AgentSession.
    """

    def dumps(self, session: AgentSession) -> dict[str, Any]:
        """Convert a session to a JSON-safe dict."""
        ...

    def loads(
        self,
        data: Union[str, dict[str, Any]],
        *,
        ctx: Any = None,
    ) -> AgentSession:
        """Parse storage JSON back into an AgentSession."""
        ...


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
        for pending in turn.get("pending_interactions", []) if False else []:
            pass
    for pending in parsed.get("pending_interactions", []):
        if pending.get("created_at") and isinstance(pending["created_at"], str):
            pending["created_at"] = datetime.fromisoformat(pending["created_at"])


class DefaultSessionCodec:
    """Canonical Nexus session JSON (model_dump / model_validate)."""

    def dumps(self, session: AgentSession) -> dict[str, Any]:
        return session.model_dump(mode="json")

    def loads(
        self,
        data: Union[str, dict[str, Any]],
        *,
        ctx: Any = None,
    ) -> AgentSession:
        parsed = json.loads(data) if isinstance(data, str) else dict(data)
        _parse_datetimes(parsed)
        return AgentSession.model_validate(parsed)


def session_to_json(session: AgentSession, *, pretty: bool = False) -> str:
    """Serialize via DefaultSessionCodec to a JSON string."""
    payload = DefaultSessionCodec().dumps(session)
    return json.dumps(payload, indent=2 if pretty else None, default=str)


def session_from_json(data: Union[str, dict[str, Any]]) -> AgentSession:
    """Deserialize via DefaultSessionCodec."""
    return DefaultSessionCodec().loads(data)


def load_codec(class_path: Optional[str] = None) -> SessionCodec:
    """Import a codec class path, or return DefaultSessionCodec."""
    if not class_path:
        return DefaultSessionCodec()
    module_path, _, name = class_path.rpartition(".")
    if not module_path:
        raise ValueError(f"Invalid codec_class path: {class_path!r}")
    module = import_module(module_path)
    cls = getattr(module, name)
    return cls() if callable(cls) else cls
