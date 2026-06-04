"""Nexus memory subsystem.

- ``MemoryCurator``: a gated, size-limited writer that extracts durable
  entity/working memory from the conversation via a separate LLM call (or a
  full curator agent). Reading is automatic via system-prompt injection.
- ``UserMemoryStore``: cross-session profile facts keyed by tenant + user.
"""

from nexus.memory.curator import MemoryCurator, MemoryUpdate
from nexus.memory.user_store import (
    InMemoryUserMemoryStore,
    SQLiteUserMemoryStore,
    UserMemoryRecord,
    UserMemoryStore,
    make_user_memory_key,
    resolve_user_namespace,
)

__all__ = [
    "MemoryCurator",
    "MemoryUpdate",
    "UserMemoryStore",
    "UserMemoryRecord",
    "InMemoryUserMemoryStore",
    "SQLiteUserMemoryStore",
    "make_user_memory_key",
    "resolve_user_namespace",
]
