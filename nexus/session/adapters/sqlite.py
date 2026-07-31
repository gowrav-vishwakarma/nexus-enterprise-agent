"""SQLite storage adapter for the Nexus Agent Framework.

Uses aiosqlite for async I/O and stores sessions as JSON blobs,
making it a zero-dependency persistent option for development and
single-server SaaS deployments.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore

from nexus.session.adapters.base import StorageAdapter
from nexus.session.codec import DefaultSessionCodec, SessionCodec
from nexus.session.models import AgentSession, TurnRecord
from nexus.session.scope import SessionScope
from nexus.storage.paths import (
    get_data_root,
    lookup_session,
    normalize_tenant_id,
    register_session,
    sessions_db_path,
    unregister_session,
)

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nexus_sessions (
    session_id  TEXT PRIMARY KEY,
    agent_id    TEXT NOT NULL,
    tenant_id   TEXT,
    user_id     TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_id   ON nexus_sessions (agent_id);
CREATE INDEX IF NOT EXISTS idx_tenant_id  ON nexus_sessions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_user_id    ON nexus_sessions (user_id);
"""


class SQLiteStorageAdapter(StorageAdapter):
    """Async SQLite session storage using aiosqlite.

    Session state is serialised as a single JSON blob in the ``data``
    column.  Separate indexed columns allow efficient listing/filtering
    without deserialising every row.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        data_root: Optional[str] = None,
        tenant_scoped: bool = True,
        wal_mode: bool = True,
        auto_migrate: bool = True,
        table_prefix: str = "nexus_",
        codec: Optional[SessionCodec] = None,
    ) -> None:
        if aiosqlite is None:
            raise ImportError(
                "aiosqlite is required for SQLiteStorageAdapter. "
                "Install it with: uv pip install aiosqlite"
            )
        self.tenant_scoped = tenant_scoped
        self.data_root = Path(data_root) if data_root else get_data_root()
        self.db_path = db_path
        self.wal_mode = wal_mode
        self.auto_migrate = auto_migrate
        self.table_prefix = table_prefix
        self._codec: SessionCodec = codec or DefaultSessionCodec()
        self._initialised_paths: set[str] = set()

    async def _resolve_location(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
        session: Optional[AgentSession] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        tid = (scope.tenant_id if scope else None) or (
            session.tenant_id if session else None
        )
        uid = (scope.user_id if scope else None) or (
            session.user_id if session else None
        )
        if tid is not None and uid is not None:
            return tid, uid
        if self.tenant_scoped:
            entry = await lookup_session(session_id, data_root=self.data_root)
            if entry:
                return entry.get("tenant_id"), entry.get("user_id")
        return tid, uid

    def _resolve_db_path(
        self,
        tenant_id: Optional[str],
        user_id: Optional[str],
    ) -> str:
        if not self.tenant_scoped:
            if not self.db_path:
                raise ValueError("db_path is required when tenant_scoped=False")
            return self.db_path
        path = sessions_db_path(tenant_id, user_id, data_root=self.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    async def _ensure_schema(self, db: "aiosqlite.Connection", db_file: str) -> None:
        if db_file not in self._initialised_paths:
            await db.executescript(_CREATE_TABLE_SQL)
            if self.wal_mode:
                await db.execute("PRAGMA journal_mode=WAL")
            await db.commit()
            self._initialised_paths.add(db_file)

    def _session_to_row(self, session: AgentSession) -> tuple:
        data = json.dumps(self._codec.dumps(session), default=str)
        return (
            session.session_id,
            session.agent_id,
            session.tenant_id,
            session.user_id,
            int(session.is_active),
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
            data,
        )

    def _row_to_session(self, row: tuple) -> AgentSession:
        return self._codec.loads(row[7])

    def _encode_session(self, session: AgentSession) -> str:
        return json.dumps(self._codec.dumps(session), default=str)

    async def save_session(self, session: AgentSession) -> None:
        tid, uid = await self._resolve_location(session.session_id, session=session)
        db_file = self._resolve_db_path(tid, uid)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            row = self._session_to_row(session)
            await db.execute(
                """
                INSERT INTO nexus_sessions
                    (session_id, agent_id, tenant_id, user_id, is_active,
                     created_at, updated_at, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    agent_id   = excluded.agent_id,
                    tenant_id  = excluded.tenant_id,
                    user_id    = excluded.user_id,
                    is_active  = excluded.is_active,
                    updated_at = excluded.updated_at,
                    data       = excluded.data
                """,
                row,
            )
            await db.commit()
        if self.tenant_scoped:
            await register_session(
                session.session_id, tid, uid, data_root=self.data_root
            )

    async def load_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> Optional[AgentSession]:
        tid, uid = await self._resolve_location(session_id, scope=scope)
        db_file = self._resolve_db_path(tid, uid)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            async with db.execute(
                "SELECT session_id, agent_id, tenant_id, user_id, is_active, "
                "created_at, updated_at, data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                session = self._row_to_session(row)
                if scope is not None and not scope.matches_session(session):
                    return None
                return session

    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        scope: Optional[SessionScope] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        tenant_id = scope.tenant_id if scope else None
        user_id = scope.user_id if scope else None

        if not self.tenant_scoped:
            return await self._list_from_db(
                self._resolve_db_path(None, None),
                agent_id,
                scope,
                limit,
                offset,
            )

        results: list[AgentSession] = []
        if tenant_id is not None and user_id is not None:
            db_files = [self._resolve_db_path(tenant_id, user_id)]
        elif tenant_id is not None:
            tenant_users = self.data_root / normalize_tenant_id(tenant_id) / "users"
            db_files = []
            if tenant_users.exists():
                for user_dir in tenant_users.iterdir():
                    if user_dir.is_dir():
                        candidate = user_dir / "sessions.db"
                        if candidate.exists():
                            db_files.append(str(candidate))
        else:
            db_files = [
                str(p)
                for p in self.data_root.rglob("sessions.db")
                if "_index" not in p.parts
            ]

        for db_file in db_files:
            batch = await self._list_from_db(
                db_file, agent_id, scope, limit + offset, 0
            )
            results.extend(batch)
            if len(results) >= offset + limit:
                break

        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results[offset : offset + limit]

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        scope: Optional[SessionScope] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        tenant_id = scope.tenant_id if scope else None
        user_id = scope.user_id if scope else None

        if not self.tenant_scoped:
            return await self._list_from_db(
                self._resolve_db_path(None, None),
                None,
                scope,
                limit=10000,
                offset=0,
                session_id_prefix=session_id_prefix,
                exclude_session_ids=exclude_session_ids,
            )

        if tenant_id is not None and user_id is not None:
            db_files = [self._resolve_db_path(tenant_id, user_id)]
        elif tenant_id is not None:
            tenant_users = self.data_root / normalize_tenant_id(tenant_id) / "users"
            db_files = []
            if tenant_users.exists():
                for user_dir in tenant_users.iterdir():
                    if user_dir.is_dir():
                        candidate = user_dir / "sessions.db"
                        if candidate.exists():
                            db_files.append(str(candidate))
        else:
            db_files = [
                str(p)
                for p in self.data_root.rglob("sessions.db")
                if "_index" not in p.parts
            ]

        results: list[AgentSession] = []
        for db_file in db_files:
            batch = await self._list_from_db(
                db_file,
                None,
                scope,
                limit=10000,
                offset=0,
                session_id_prefix=session_id_prefix,
                exclude_session_ids=exclude_session_ids,
            )
            results.extend(batch)

        results.sort(key=lambda s: s.created_at)
        return results

    async def _list_from_db(
        self,
        db_file: str,
        agent_id: Optional[str],
        scope: Optional[SessionScope],
        limit: int,
        offset: int,
        session_id_prefix: Optional[str] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        if not Path(db_file).exists():
            return []

        tenant_id = scope.tenant_id if scope else None
        user_id = scope.user_id if scope else None

        conditions: list[str] = []
        params: list = []

        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if session_id_prefix:
            conditions.append("session_id LIKE ?")
            params.append(f"{session_id_prefix}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order = "created_at ASC" if session_id_prefix else "updated_at DESC"
        params.extend([limit, offset])

        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            async with db.execute(
                f"SELECT session_id, agent_id, tenant_id, user_id, is_active, "
                f"created_at, updated_at, data FROM nexus_sessions "
                f"{where} ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ) as cursor:
                rows = await cursor.fetchall()
                sessions = [self._row_to_session(r) for r in rows]
                if scope is not None:
                    sessions = [s for s in sessions if scope.matches_session(s)]
                if exclude_session_ids:
                    sessions = [
                        s for s in sessions if s.session_id not in exclude_session_ids
                    ]
                return sessions

    async def delete_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        tid, uid = await self._resolve_location(session_id, scope=scope)
        db_file = self._resolve_db_path(tid, uid)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            await db.execute(
                "DELETE FROM nexus_sessions WHERE session_id = ?", (session_id,)
            )
            await db.commit()
        if self.tenant_scoped:
            await unregister_session(session_id, data_root=self.data_root)

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        tid, uid = await self._resolve_location(session_id, scope=scope)
        db_file = self._resolve_db_path(tid, uid)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            async with db.execute(
                "SELECT data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    logger.warning("append_turn: session %s not found", session_id)
                    return

            session = self._codec.loads(row[0])
            if scope is not None and not scope.matches_session(session):
                logger.warning("append_turn: session %s scope mismatch", session_id)
                return
            session.turns.append(turn)
            session.updated_at = datetime.now()

            await db.execute(
                "UPDATE nexus_sessions SET data = ?, updated_at = ? WHERE session_id = ?",
                (self._encode_session(session), session.updated_at.isoformat(), session_id),
            )
            await db.commit()

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        tid, uid = await self._resolve_location(session_id, scope=scope)
        db_file = self._resolve_db_path(tid, uid)
        async with aiosqlite.connect(db_file) as db:
            await self._ensure_schema(db, db_file)
            async with db.execute(
                "SELECT data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return

            session = self._codec.loads(row[0])
            if scope is not None and not scope.matches_session(session):
                return
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        tc.summarized_response = summarized_response
                        tc.summarized_by_turn = summarized_by_turn
                        break

            session.updated_at = datetime.now()
            await db.execute(
                "UPDATE nexus_sessions SET data = ?, updated_at = ? WHERE session_id = ?",
                (self._encode_session(session), session.updated_at.isoformat(), session_id),
            )
            await db.commit()
