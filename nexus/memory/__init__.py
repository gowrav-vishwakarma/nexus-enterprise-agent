"""Memory components for the Nexus Agent Framework.

- ``MemoryCurator``: gated writer for per-session entity/working memory.
- ``CrossSessionMemoryStore``: durable profile facts keyed by tenant + user.
"""

from nexus.memory.curator import MemoryCurator, MemoryUpdate
from nexus.memory.cross_session_store import (
    InMemoryCrossSessionMemoryStore,
    SQLiteCrossSessionMemoryStore,
    CrossSessionMemoryRecord,
    CrossSessionMemoryStore,
    make_cross_session_memory_key,
    resolve_cross_session_namespace,
)

__all__ = [
    "MemoryCurator",
    "MemoryUpdate",
    "CrossSessionMemoryStore",
    "CrossSessionMemoryRecord",
    "InMemoryCrossSessionMemoryStore",
    "SQLiteCrossSessionMemoryStore",
    "make_cross_session_memory_key",
    "resolve_cross_session_namespace",
]
