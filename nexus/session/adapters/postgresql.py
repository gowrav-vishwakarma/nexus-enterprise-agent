"""PostgreSQL session storage adapter."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore

from nexus.session.adapters.base import StorageAdapter
from nexus.session.codec import DefaultSessionCodec, SessionCodec
from nexus.session.models import AgentSession, TurnRecord
from nexus.session.scope import SessionScope

logger = logging.getLogger(__name__)

SchemaMode = Literal["managed", "existing", "qualified"]

_CREATE_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    session_id  TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    tenant_id   TEXT,
    user_id     TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    data        JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_{idx_prefix}sessions_tenant_user
    ON {table} (tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_{idx_prefix}sessions_agent
    ON {table} (agent_id);
CREATE INDEX IF NOT EXISTS idx_{idx_prefix}sessions_created
    ON {table} (created_at);
"""


def _resolve_table_name(
    *,
    sessions_table: Optional[str],
    table_prefix: str,
    db_schema: Optional[str],
    schema_mode: SchemaMode,
) -> str:
    if sessions_table:
        if "." in sessions_table:
            return sessions_table
        if db_schema and schema_mode == "qualified":
            return f'"{db_schema}".{sessions_table}'
        if db_schema:
            return f'"{db_schema}".{sessions_table}'
        return sessions_table
    base = f"{table_prefix}sessions"
    if db_schema and schema_mode == "qualified":
        return f'"{db_schema}".{base}'
    return base


def _index_prefix(table: str) -> str:
    return table.replace(".", "_").replace('"', "")


class PostgreSQLStorageAdapter(StorageAdapter):
    """Async PostgreSQL session storage using asyncpg and JSONB blobs."""

    def __init__(
        self,
        dsn: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
        schema: Optional[str] = None,
        db_schema: Optional[str] = None,
        schema_mode: SchemaMode = "managed",
        sessions_table: Optional[str] = None,
        table_prefix: str = "nexus_",
        auto_migrate: bool = False,
        connect_args: Optional[dict[str, Any]] = None,
        pool: Any = None,
        codec: Optional[SessionCodec] = None,
    ) -> None:
        if asyncpg is None:
            raise ImportError(
                "asyncpg is required for PostgreSQLStorageAdapter. "
                "Install with: pip install nexus-enterprise-agent[postgres]"
            )
        self.dsn = dsn
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.db_schema = db_schema if db_schema is not None else schema
        self.schema_mode: SchemaMode = schema_mode
        self.table_prefix = table_prefix
        self.auto_migrate = auto_migrate
        self.connect_args = connect_args or {}
        self._pool = pool
        self._owns_pool = pool is None
        self._schema_ready = False
        self._codec: SessionCodec = codec or DefaultSessionCodec()
        self.sessions_table = _resolve_table_name(
            sessions_table=sessions_table,
            table_prefix=table_prefix,
            db_schema=self.db_schema,
            schema_mode=self.schema_mode,
        )

    async def _get_pool(self) -> "asyncpg.Pool":
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,
                max_size=self.pool_size + self.max_overflow,
                **self.connect_args,
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
            idx = _index_prefix(self.sessions_table)
            ddl = _CREATE_SESSIONS_DDL.format(
                table=self.sessions_table,
                idx_prefix=idx,
            )
            await conn.execute(ddl)
        self._schema_ready = True

    def _encode_session(self, session: AgentSession) -> str:
        return json.dumps(self._codec.dumps(session), default=str)

    def _session_to_row(self, session: AgentSession) -> tuple:
        return (
            session.session_id,
            session.agent_id,
            session.tenant_id,
            session.user_id,
            session.is_active,
            session.created_at,
            session.updated_at,
            self._encode_session(session),
        )

    async def save_session(self, session: AgentSession) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(
                    f'SET search_path TO "{self.db_schema}", public'
                )
            await self._ensure_schema(conn)
            row = self._session_to_row(session)
            await conn.execute(
                f"""
                INSERT INTO {self.sessions_table}
                    (session_id, agent_id, tenant_id, user_id, is_active,
                     created_at, updated_at, data)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                ON CONFLICT (session_id) DO UPDATE SET
                    agent_id   = EXCLUDED.agent_id,
                    tenant_id  = EXCLUDED.tenant_id,
                    user_id    = EXCLUDED.user_id,
                    is_active  = EXCLUDED.is_active,
                    updated_at = EXCLUDED.updated_at,
                    data       = EXCLUDED.data
                """,
                *row,
            )

    async def load_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> Optional[AgentSession]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(
                    f'SET search_path TO "{self.db_schema}", public'
                )
            await self._ensure_schema(conn)
            conditions = ["session_id = $1"]
            params: list[Any] = [session_id]
            if scope is not None:
                if scope.tenant_id is not None:
                    conditions.append(f"tenant_id = ${len(params) + 1}")
                    params.append(scope.tenant_id)
                if scope.user_id is not None:
                    conditions.append(f"user_id = ${len(params) + 1}")
                    params.append(scope.user_id)
            where = " AND ".join(conditions)
            row = await conn.fetchrow(
                f"SELECT data FROM {self.sessions_table} WHERE {where}",
                *params,
            )
            if row is None:
                return None
            session = self._codec.loads(row["data"])
            if scope is not None and not scope.matches_session(session):
                return None
            return session

    async def _list_query(
        self,
        *,
        agent_id: Optional[str],
        scope: Optional[SessionScope],
        session_id_prefix: Optional[str],
        exclude_session_ids: Optional[set[str]],
        limit: int,
        offset: int,
    ) -> list[AgentSession]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(
                    f'SET search_path TO "{self.db_schema}", public'
                )
            await self._ensure_schema(conn)
            conditions: list[str] = []
            params: list[Any] = []
            n = 1

            def add(cond: str, val: Any) -> None:
                nonlocal n
                conditions.append(cond.replace("?", f"${n}"))
                params.append(val)
                n += 1

            if agent_id:
                add("agent_id = ?", agent_id)
            if scope is not None:
                if scope.tenant_id is not None:
                    add("tenant_id = ?", scope.tenant_id)
                if scope.user_id is not None:
                    add("user_id = ?", scope.user_id)
            if session_id_prefix:
                add("session_id LIKE ?", f"{session_id_prefix}%")

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            order = "created_at ASC" if session_id_prefix else "updated_at DESC"
            params.extend([limit, offset])
            rows = await conn.fetch(
                f"SELECT data FROM {self.sessions_table} {where} "
                f"ORDER BY {order} LIMIT ${n} OFFSET ${n + 1}",
                *params,
            )
            sessions = [self._codec.loads(r["data"]) for r in rows]
            if scope is not None:
                sessions = [s for s in sessions if scope.matches_session(s)]
            if exclude_session_ids:
                sessions = [
                    s for s in sessions if s.session_id not in exclude_session_ids
                ]
            return sessions

    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        scope: Optional[SessionScope] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        return await self._list_query(
            agent_id=agent_id,
            scope=scope,
            session_id_prefix=None,
            exclude_session_ids=None,
            limit=limit,
            offset=offset,
        )

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        scope: Optional[SessionScope] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        return await self._list_query(
            agent_id=None,
            scope=scope,
            session_id_prefix=session_id_prefix,
            exclude_session_ids=exclude_session_ids,
            limit=10000,
            offset=0,
        )

    async def delete_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(
                    f'SET search_path TO "{self.db_schema}", public'
                )
            await self._ensure_schema(conn)
            conditions = ["session_id = $1"]
            params: list[Any] = [session_id]
            if scope is not None:
                if scope.tenant_id is not None:
                    conditions.append(f"tenant_id = ${len(params) + 1}")
                    params.append(scope.tenant_id)
                if scope.user_id is not None:
                    conditions.append(f"user_id = ${len(params) + 1}")
                    params.append(scope.user_id)
            where = " AND ".join(conditions)
            await conn.execute(
                f"DELETE FROM {self.sessions_table} WHERE {where}",
                *params,
            )

    async def _load_mutate_save(
        self,
        session_id: str,
        mutator,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if self.schema_mode != "qualified" and self.db_schema:
                await conn.execute(
                    f'SET search_path TO "{self.db_schema}", public'
                )
            await self._ensure_schema(conn)
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"SELECT data FROM {self.sessions_table} "
                    f"WHERE session_id = $1 FOR UPDATE",
                    session_id,
                )
                if row is None:
                    logger.warning("session %s not found for mutation", session_id)
                    return
                session = self._codec.loads(row["data"])
                if scope is not None and not scope.matches_session(session):
                    logger.warning("session %s scope mismatch for mutation", session_id)
                    return
                mutator(session)
                session.updated_at = datetime.now()
                await conn.execute(
                    f"UPDATE {self.sessions_table} SET data = $1::jsonb, "
                    f"updated_at = $2 WHERE session_id = $3",
                    self._encode_session(session),
                    session.updated_at,
                    session_id,
                )

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        def mutate(session: AgentSession) -> None:
            session.turns.append(turn)

        await self._load_mutate_save(session_id, mutate, scope=scope)

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        def mutate(session: AgentSession) -> None:
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        tc.summarized_response = summarized_response
                        tc.summarized_by_turn = summarized_by_turn
                        if summarized_response == "[]":
                            tc.is_dropped = True
                        return

        await self._load_mutate_save(session_id, mutate, scope=scope)
