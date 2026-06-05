"""Tenant-scoped storage path resolution and session index."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Optional, Union

_DataRoot = Union[str, Path]

_DEFAULT_TENANT = "_default"
_DEFAULT_USER = "_default"
_UNSAFE_SEGMENT_RE = re.compile(r"[/\\:\0]|\.\.")

_index_lock = asyncio.Lock()


def get_data_root() -> Path:
    """Return the storage root directory (default ./tenants, overridable via NEXUS_DATA_ROOT)."""
    return Path(os.getenv("NEXUS_DATA_ROOT", "./tenants"))


def _coerce_data_root(data_root: Optional[_DataRoot]) -> Path:
    return Path(data_root) if data_root is not None else get_data_root()


def sanitize_segment(value: Optional[str], *, fallback: str) -> str:
    """Sanitize a path segment; return fallback when value is missing or empty."""
    if not value or not str(value).strip():
        return fallback
    cleaned = _UNSAFE_SEGMENT_RE.sub("_", str(value).strip())
    return cleaned or fallback


def normalize_tenant_id(tenant_id: Optional[str]) -> str:
    return sanitize_segment(tenant_id, fallback=_DEFAULT_TENANT)


def normalize_user_id(user_id: Optional[str]) -> str:
    return sanitize_segment(user_id, fallback=_DEFAULT_USER)


def tenant_user_dir(
    tenant_id: Optional[str],
    user_id: Optional[str],
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/."""
    root = _coerce_data_root(data_root)
    tenant = normalize_tenant_id(tenant_id)
    user = normalize_user_id(user_id)
    return root / tenant / "users" / user


def session_dir(
    tenant_id: Optional[str],
    user_id: Optional[str],
    session_id: str,
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/{session_id}/."""
    safe_session = sanitize_segment(session_id, fallback=session_id)
    return tenant_user_dir(tenant_id, user_id, data_root=data_root) / safe_session


def session_file(
    tenant_id: Optional[str],
    user_id: Optional[str],
    session_id: str,
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/{session_id}/session.json."""
    return session_dir(tenant_id, user_id, session_id, data_root=data_root) / "session.json"


def session_lock_file(
    tenant_id: Optional[str],
    user_id: Optional[str],
    session_id: str,
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/{session_id}/.session.lock."""
    return session_dir(tenant_id, user_id, session_id, data_root=data_root) / ".session.lock"


def memory_db_path(
    tenant_id: Optional[str],
    user_id: Optional[str],
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/memory.db."""
    return tenant_user_dir(tenant_id, user_id, data_root=data_root) / "memory.db"


def sessions_db_path(
    tenant_id: Optional[str],
    user_id: Optional[str],
    *,
    data_root: Optional[_DataRoot] = None,
) -> Path:
    """Return tenants/{tenant_id}/users/{user_id}/sessions.db."""
    return tenant_user_dir(tenant_id, user_id, data_root=data_root) / "sessions.db"


def session_index_path(*, data_root: Optional[_DataRoot] = None) -> Path:
    """Return {data_root}/_index/sessions.json."""
    root = _coerce_data_root(data_root)
    return root / "_index" / "sessions.json"


def _read_index_sync(data_root: Path) -> dict[str, dict[str, Optional[str]]]:
    path = session_index_path(data_root=data_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_index_sync(data_root: Path, index: dict[str, dict[str, Optional[str]]]) -> None:
    path = session_index_path(data_root=data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=2))


async def register_session(
    session_id: str,
    tenant_id: Optional[str],
    user_id: Optional[str],
    *,
    data_root: Optional[_DataRoot] = None,
) -> None:
    """Record session_id -> tenant/user mapping for lookup without hints."""
    root = _coerce_data_root(data_root)
    async with _index_lock:
        index = await asyncio.to_thread(_read_index_sync, root)
        index[session_id] = {"tenant_id": tenant_id, "user_id": user_id}
        await asyncio.to_thread(_write_index_sync, root, index)


async def unregister_session(
    session_id: str,
    *,
    data_root: Optional[_DataRoot] = None,
) -> None:
    """Remove a session from the index."""
    root = _coerce_data_root(data_root)
    async with _index_lock:
        index = await asyncio.to_thread(_read_index_sync, root)
        index.pop(session_id, None)
        await asyncio.to_thread(_write_index_sync, root, index)


async def lookup_session(
    session_id: str,
    *,
    data_root: Optional[_DataRoot] = None,
) -> Optional[dict[str, Optional[str]]]:
    """Look up tenant_id and user_id for a session_id."""
    root = _coerce_data_root(data_root)
    async with _index_lock:
        index = await asyncio.to_thread(_read_index_sync, root)
    entry = index.get(session_id)
    if entry is None:
        return None
    return {"tenant_id": entry.get("tenant_id"), "user_id": entry.get("user_id")}


def default_file_storage_config() -> dict[str, Any]:
    """Default adapter_config for tenant-scoped file storage."""
    return {
        "data_root": str(get_data_root()),
        "tenant_scoped": True,
    }


def default_sqlite_storage_config() -> dict[str, Any]:
    """Default adapter_config for tenant-scoped SQLite session storage."""
    return {
        "data_root": str(get_data_root()),
        "tenant_scoped": True,
    }
