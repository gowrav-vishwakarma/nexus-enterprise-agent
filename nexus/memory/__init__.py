"""Memory components for the Nexus Agent Framework.

- ``MemoryCurator``: gated writer for cross-session user facts.
- ``CrossSessionMemoryStore``: durable profile facts keyed by tenant + user.
"""

from nexus.memory.curator import MemoryCurator, MemoryUpdate
from nexus.memory.cross_session_store import (
    InMemoryCrossSessionMemoryStore,
    PostgreSQLCrossSessionMemoryStore,
    RedisCrossSessionMemoryStore,
    SQLiteCrossSessionMemoryStore,
    CrossSessionMemoryRecord,
    CrossSessionMemoryStore,
    make_cross_session_memory_key,
    resolve_cross_session_namespace,
)
from nexus.memory.provider import MemoryProvider, MemoryProviderProtocol
from nexus.memory.providers.builtin_semantic import BuiltInSemanticMemoryProvider

__all__ = [
    "MemoryCurator",
    "MemoryUpdate",
    "CrossSessionMemoryStore",
    "CrossSessionMemoryRecord",
    "InMemoryCrossSessionMemoryStore",
    "SQLiteCrossSessionMemoryStore",
    "PostgreSQLCrossSessionMemoryStore",
    "RedisCrossSessionMemoryStore",
    "make_cross_session_memory_key",
    "resolve_cross_session_namespace",
    "MemoryProvider",
    "MemoryProviderProtocol",
    "BuiltInSemanticMemoryProvider",
]
