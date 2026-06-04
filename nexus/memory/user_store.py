"""Cross-session user memory store (tenant + user + namespace)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CREATE_USER_MEMORY_SQL = """
CREATE TABLE IF NOT EXISTS nexus_user_memory (
    memory_key  TEXT PRIMARY KEY,
    tenant_id   TEXT,
    user_id     TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_memory_tenant ON nexus_user_memory (tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_memory_user   ON nexus_user_memory (user_id);
"""


def make_user_memory_key(
    tenant_id: Optional[str],
    user_id: str,
    namespace: str,
) -> str:
    """Build a stable storage key for a user memory record."""
    tenant_part = tenant_id or "_"
    return f"{tenant_part}:{user_id}:{namespace}"


def resolve_user_namespace(configured: str, agent_name: str) -> str:
    """Return the namespace for user memory (defaults to agent name)."""
    return configured.strip() or agent_name


class UserMemoryRecord(BaseModel):
    """Durable facts for one user within a tenant/namespace scope."""

    tenant_id: Optional[str] = None
    user_id: str
    namespace: str
    entity_memory: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


@runtime_checkable
class UserMemoryStore(Protocol):
    """Protocol for cross-session user memory persistence."""

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[UserMemoryRecord]: ...

    async def save(self, record: UserMemoryRecord) -> None: ...

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
    ) -> UserMemoryRecord:
        """Merge entities into the user record, enforcing max_entities cap."""
        ...


def _cap_entities(entities: dict[str, str], max_entities: int) -> dict[str, str]:
    if len(entities) <= max_entities:
        return entities
    return dict(list(entities.items())[-max_entities:])


class InMemoryUserMemoryStore:
    """In-process user memory store for tests and dev."""

    def __init__(self) -> None:
        self._records: dict[str, UserMemoryRecord] = {}

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[UserMemoryRecord]:
        key = make_user_memory_key(tenant_id, user_id, namespace)
        return self._records.get(key)

    async def save(self, record: UserMemoryRecord) -> None:
        key = make_user_memory_key(record.tenant_id, record.user_id, record.namespace)
        record.touch()
        self._records[key] = record

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
    ) -> UserMemoryRecord:
        existing = await self.load(tenant_id, user_id, namespace)
        if existing is None:
            existing = UserMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing)
        return existing


class SQLiteUserMemoryStore:
    """SQLite-backed user memory store."""

    def __init__(self, db_path: str = "./nexus_user_memory.db") -> None:
        try:
            import aiosqlite  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "aiosqlite is required for SQLiteUserMemoryStore. "
                "Install it with: uv pip install aiosqlite"
            ) from exc
        self.db_path = db_path
        self._initialised = False

    async def _ensure_schema(self, db) -> None:
        if not self._initialised:
            await db.executescript(_CREATE_USER_MEMORY_SQL)
            await db.commit()
            self._initialised = True

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[UserMemoryRecord]:
        import aiosqlite

        key = make_user_memory_key(tenant_id, user_id, namespace)
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            async with db.execute(
                "SELECT data FROM nexus_user_memory WHERE memory_key = ?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return UserMemoryRecord(**json.loads(row[0]))

    async def save(self, record: UserMemoryRecord) -> None:
        import aiosqlite

        record.touch()
        key = make_user_memory_key(record.tenant_id, record.user_id, record.namespace)
        data = record.model_dump_json()
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute(
                """
                INSERT INTO nexus_user_memory
                    (memory_key, tenant_id, user_id, namespace, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_key) DO UPDATE SET
                    tenant_id  = excluded.tenant_id,
                    user_id    = excluded.user_id,
                    namespace  = excluded.namespace,
                    updated_at = excluded.updated_at,
                    data       = excluded.data
                """,
                (
                    key,
                    record.tenant_id,
                    record.user_id,
                    record.namespace,
                    record.updated_at.isoformat(),
                    data,
                ),
            )
            await db.commit()

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
    ) -> UserMemoryRecord:
        existing = await self.load(tenant_id, user_id, namespace)
        if existing is None:
            existing = UserMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing)
        return existing
