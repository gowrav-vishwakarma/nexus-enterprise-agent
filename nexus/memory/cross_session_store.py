"""Cross-session memory store (tenant + user + namespace)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

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
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]: ...

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None: ...

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
        company_id: Optional[str] = None,
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
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]:
        del company_id  # built-in stores key by tenant+user+namespace only
        key = make_cross_session_memory_key(tenant_id, user_id, namespace)
        return self._records.get(key)

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None:
        del company_id
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
        company_id: Optional[str] = None,
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(
            tenant_id, user_id, namespace, company_id=company_id
        )
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing, company_id=company_id)
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
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]:
        import aiosqlite

        del company_id
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

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None:
        import aiosqlite

        del company_id
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
        company_id: Optional[str] = None,
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(
            tenant_id, user_id, namespace, company_id=company_id
        )
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing, company_id=company_id)
        return existing


_CREATE_USER_MEMORY_PG = """
CREATE TABLE IF NOT EXISTS {table} (
    memory_key  TEXT PRIMARY KEY,
    tenant_id   TEXT,
    user_id     TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    data        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{idx_prefix}user_memory_user ON {table} (user_id);
"""


class PostgreSQLCrossSessionMemoryStore:
    """PostgreSQL-backed cross-session memory store."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: Optional[str] = None,
        db_schema: Optional[str] = None,
        schema_mode: str = "managed",
        user_memory_table: Optional[str] = None,
        table_prefix: str = "nexus_",
        auto_migrate: bool = False,
        connect_args: Optional[dict[str, Any]] = None,
        pool: Any = None,
    ) -> None:
        from nexus.session.adapters.postgresql import _index_prefix, _resolve_table_name

        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for PostgreSQLCrossSessionMemoryStore. "
                "Install with: pip install nexus-enterprise-agent[postgres]"
            ) from exc

        self.dsn = dsn
        self.db_schema = db_schema if db_schema is not None else schema
        self.schema_mode = schema_mode
        self.auto_migrate = auto_migrate
        self.connect_args = connect_args or {}
        self._pool = pool
        self._owns_pool = pool is None
        self._schema_ready = False
        self.memory_table = user_memory_table or _resolve_table_name(
            sessions_table=f"{table_prefix}user_memory",
            table_prefix=table_prefix,
            db_schema=self.db_schema,
            schema_mode=schema_mode,  # type: ignore[arg-type]
        )
        self._idx_prefix = _index_prefix(self.memory_table)

    async def _get_pool(self):
        import asyncpg

        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.dsn, min_size=1, max_size=10, **self.connect_args
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
            self._pool = None

    async def _ensure_schema(self, conn) -> None:
        if self._schema_ready:
            return
        if self.schema_mode == "existing":
            self._schema_ready = True
            return
        if self.schema_mode == "managed" and self.auto_migrate:
            ddl = _CREATE_USER_MEMORY_PG.format(
                table=self.memory_table,
                idx_prefix=self._idx_prefix,
            )
            await conn.execute(ddl)
        self._schema_ready = True

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]:
        del company_id
        key = make_cross_session_memory_key(tenant_id, user_id, namespace)
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(f'SET search_path TO "{self.db_schema}", public')
            await self._ensure_schema(conn)
            row = await conn.fetchrow(
                f"SELECT data FROM {self.memory_table} WHERE memory_key = $1",
                key,
            )
        if not row:
            return None
        data = row["data"]
        if isinstance(data, str):
            return CrossSessionMemoryRecord(**json.loads(data))
        return CrossSessionMemoryRecord(**data)

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None:
        del company_id
        record.touch()
        key = make_cross_session_memory_key(record.tenant_id, record.user_id, record.namespace)
        payload = record.model_dump_json()
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(f'SET search_path TO "{self.db_schema}", public')
            await self._ensure_schema(conn)
            await conn.execute(
                f"""
                INSERT INTO {self.memory_table}
                    (memory_key, tenant_id, user_id, namespace, updated_at, data)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                ON CONFLICT (memory_key) DO UPDATE SET
                    tenant_id  = EXCLUDED.tenant_id,
                    user_id    = EXCLUDED.user_id,
                    namespace  = EXCLUDED.namespace,
                    updated_at = EXCLUDED.updated_at,
                    data       = EXCLUDED.data
                """,
                key,
                record.tenant_id,
                record.user_id,
                record.namespace,
                record.updated_at,
                payload,
            )

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
        company_id: Optional[str] = None,
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(
            tenant_id, user_id, namespace, company_id=company_id
        )
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing, company_id=company_id)
        return existing


class RedisCrossSessionMemoryStore:
    """Redis-backed cross-session memory store."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        key_prefix: str = "nexus:",
        memory_key_template: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        max_connections: int = 50,
        client: Any = None,
    ) -> None:
        try:
            import redis.asyncio  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "redis is required for RedisCrossSessionMemoryStore. "
                "Install with: pip install nexus-enterprise-agent[redis]"
            ) from exc

        self.memory_key_template = memory_key_template or "{prefix}xmem:{memory_key}"
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self._owns_client = client is None
        if client is not None:
            self._redis = client
        elif url:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                url, max_connections=max_connections, decode_responses=True
            )
        else:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                max_connections=max_connections,
                decode_responses=True,
            )

    async def close(self) -> None:
        if self._owns_client and self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    def _storage_key(self, memory_key: str) -> str:
        return self.memory_key_template.format(prefix=self.key_prefix, memory_key=memory_key)

    async def load(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        *,
        company_id: Optional[str] = None,
    ) -> Optional[CrossSessionMemoryRecord]:
        del company_id
        key = make_cross_session_memory_key(tenant_id, user_id, namespace)
        raw = await self._redis.get(self._storage_key(key))
        if not raw:
            return None
        return CrossSessionMemoryRecord(**json.loads(raw))

    async def save(
        self,
        record: CrossSessionMemoryRecord,
        *,
        company_id: Optional[str] = None,
    ) -> None:
        del company_id
        record.touch()
        key = make_cross_session_memory_key(record.tenant_id, record.user_id, record.namespace)
        storage_key = self._storage_key(key)
        await self._redis.set(storage_key, record.model_dump_json())
        if self.ttl_seconds:
            await self._redis.expire(storage_key, self.ttl_seconds)

    async def merge_entities(
        self,
        tenant_id: Optional[str],
        user_id: str,
        namespace: str,
        entities: dict[str, str],
        *,
        max_entities: int,
        company_id: Optional[str] = None,
    ) -> CrossSessionMemoryRecord:
        existing = await self.load(
            tenant_id, user_id, namespace, company_id=company_id
        )
        if existing is None:
            existing = CrossSessionMemoryRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                namespace=namespace,
            )
        if entities:
            merged = {**existing.entity_memory, **entities}
            existing.entity_memory = _cap_entities(merged, max_entities)
        await self.save(existing, company_id=company_id)
        return existing
