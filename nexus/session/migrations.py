"""Session schema versioning and migrations."""

from __future__ import annotations

from typing import Any

CURRENT_SESSION_SCHEMA_VERSION = 1


def migrate_session_data(data: dict[str, Any]) -> dict[str, Any]:
    """Apply migrations to loaded session JSON."""
    version = data.get("schema_version", 0)
    if version < 1:
        data.setdefault("state", {})
        data["schema_version"] = 1
    return data
