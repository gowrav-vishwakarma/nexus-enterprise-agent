"""Cross-session memory store (tenant + user + namespace)."""

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


def make_cross_session_memory_key(
    tenant_id: Optional[str],
    user_id: str,
    namespace: str,
) -> str:
    """Build a stable storage key for a cross-session memory record."""
    tenant_part = tenant_id or "_"
    return f"{tenant_part}:{user_id}:{namespace}"


def resolve_cross_session_namespace(configured: str, agent_name: str) -> str:
    """Return the namespace for cross-session memory (defaults to agent name)."""
    return configured.strip() or agent_name


class CrossSessionMemoryRecord(BaseModel):
    """Durable facts for one user within a tenant/namespace scope."""

    tenant_id: Optional[str] = None
    user_id: str
    namespace: str
    entity_memory: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


@runtime_checkable
class CrossSessionMemoryStore(Protocol):
    """Protocol for cross-session memory persistence."""

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[CrossSessionMemoryRecord]: ...

    async def save(self, record: CrossSessionMemoryRecord) -> None: ...

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
    ) -> CrossSessionMemoryRecord:
        """Merge entities into the record, enforcing max_entities cap."""
        ...


def _cap_entities(entities: dict[str, str], max_entities: int) -> dict[str, str]:
    if len(entities) <= max_entities:
        return entities
    return dict(list(entities.items())[-max_entities:])


class InMemoryCrossSessionMemoryStore:
    """In-process cross-session memory store for tests and dev."""

    def __init__(self) -> None:
        self._records: dict[str, CrossSessionMemoryRecord] = {}

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[CrossSessionMemoryRecord]:
        key = make_cross_session_memory_key(tenant_id, user_id, namespace)
        return self._records.get(key)

    async def save(self, record: CrossSessionMemoryRecord) -> None:
        key = make_cross_session_memory_key(record.tenant_id, record.user_id, record.namespace)
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
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(tenant_id, user_id, namespace)
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing)
        return existing


class SQLiteCrossSessionMemoryStore:
    """SQLite-backed cross-session memory store."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        data_root: Optional[str] = None,
        tenant_scoped: bool = True,
    ) -> None:
        try:
            import aiosqlite  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "aiosqlite is required for SQLiteCrossSessionMemoryStore. "
                "Install it with: uv pip install aiosqlite"
            ) from exc
        from pathlib import Path

        from nexus.storage.paths import get_data_root, memory_db_path

        self.tenant_scoped = tenant_scoped
        self.data_root = Path(data_root) if data_root else get_data_root()
        self.db_path = db_path
        self._initialised_paths: set[str] = set()
        self._memory_db_path = memory_db_path

    def _resolve_db_path(self, tenant_id: Optional[str], user_id: str) -> str:
        if not self.tenant_scoped:
            if not self.db_path:
                raise ValueError("db_path is required when tenant_scoped=False")
            return self.db_path
        path = self._memory_db_path(tenant_id, user_id, data_root=self.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    async def _ensure_schema(self, db, db_file: str) -> None:
        if db_file not in self._initialised_paths:
            await db.executescript(_CREATE_USER_MEMORY_SQL)
            await db.commit()
            self._initialised_paths.add(db_file)

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
    ) -> Optional[CrossSessionMemoryRecord]:
        import aiosqlite

        key = make_cross_session_memory_key(tenant_id, user_id, namespace)
        db_file = self._resolve_db_path(tenant_id, user_id)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            async with db.execute(
                "SELECT data FROM nexus_user_memory WHERE memory_key = ?",
                (key,),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return CrossSessionMemoryRecord(**json.loads(row[0]))

    async def save(self, record: CrossSessionMemoryRecord) -> None:
        import aiosqlite

        record.touch()
        key = make_cross_session_memory_key(record.tenant_id, record.user_id, record.namespace)
        data = record.model_dump_json()
        db_file = self._resolve_db_path(record.tenant_id, record.user_id)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
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
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(tenant_id, user_id, namespace)
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing)
        return existing
