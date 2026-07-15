"""Storage adapters for the Nexus Agent Framework."""

from nexus.session.adapters.base import StorageAdapter
from nexus.session.adapters.base_sql import BaseSQLStorageAdapter
from nexus.session.adapters.memory import MemoryStorageAdapter
from nexus.session.adapters.file import FileStorageAdapter
from nexus.session.adapters.sqlite import SQLiteStorageAdapter
from nexus.session.adapters.postgresql import PostgreSQLStorageAdapter
from nexus.session.adapters.redis import RedisStorageAdapter
from nexus.session.adapters.aitalk_chats import AiTalkChatsMemoryAdapter

__all__ = [
    "StorageAdapter",
    "BaseSQLStorageAdapter",
    "MemoryStorageAdapter",
    "FileStorageAdapter",
    "SQLiteStorageAdapter",
    "PostgreSQLStorageAdapter",
    "RedisStorageAdapter",
    "AiTalkChatsMemoryAdapter",
]
