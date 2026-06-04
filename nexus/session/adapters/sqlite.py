"""SQLite storage adapter for the Nexus Agent Framework.

Uses aiosqlite for async I/O and stores sessions as JSON blobs,
making it a zero-dependency persistent option for development and
single-server SaaS deployments.
"""

import json
import logging
from datetime import datetime
from typing import Optional

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore

from nexus.session.adapters.base import StorageAdapter
from nexus.session.models import AgentSession, TurnRecord

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

    def __init__(self, db_path: str = "./nexus_sessions.db") -> None:
        if aiosqlite is None:
            raise ImportError(
                "aiosqlite is required for SQLiteStorageAdapter. "
                "Install it with: uv pip install aiosqlite"
            )
        self.db_path = db_path
        self._initialised = False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _ensure_schema(self, db: "aiosqlite.Connection") -> None:
        if not self._initialised:
            await db.executescript(_CREATE_TABLE_SQL)
            await db.commit()
            self._initialised = True

    def _session_to_row(self, session: AgentSession) -> tuple:
        data = session.model_dump_json()
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
        # row: (session_id, agent_id, tenant_id, user_id, is_active, created_at, updated_at, data)
        data = json.loads(row[7])
        return AgentSession(**data)

    # ── StorageAdapter interface ──────────────────────────────────────────────

    async def save_session(self, session: AgentSession) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
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

    async def load_session(self, session_id: str) -> Optional[AgentSession]:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            async with db.execute(
                "SELECT session_id, agent_id, tenant_id, user_id, is_active, "
                "created_at, updated_at, data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return self._row_to_session(row)

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
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

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            async with db.execute(
                f"SELECT session_id, agent_id, tenant_id, user_id, is_active, "
                f"created_at, updated_at, data FROM nexus_sessions "
                f"{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params,
            ) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_session(r) for r in rows]

    async def delete_session(self, session_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            await db.execute(
                "DELETE FROM nexus_sessions WHERE session_id = ?", (session_id,)
            )
            await db.commit()

    async def append_turn(self, session_id: str, turn: TurnRecord) -> None:
        """Load → mutate → save in a single connection to avoid races."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            async with db.execute(
                "SELECT data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    logger.warning("append_turn: session %s not found", session_id)
                    return

            session = AgentSession(**json.loads(row[0]))
            session.turns.append(turn)
            session.updated_at = datetime.now()

            await db.execute(
                "UPDATE nexus_sessions SET data = ?, updated_at = ? WHERE session_id = ?",
                (session.model_dump_json(), session.updated_at.isoformat(), session_id),
            )
            await db.commit()

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_schema(db)
            async with db.execute(
                "SELECT data FROM nexus_sessions WHERE session_id = ?",
                (session_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return

            session = AgentSession(**json.loads(row[0]))
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        tc.summarized_response = summarized_response
                        tc.summarized_by_turn = summarized_by_turn
                        if summarized_response == "[]":
                            tc.is_dropped = True
                        break

            session.updated_at = datetime.now()
            await db.execute(
                "UPDATE nexus_sessions SET data = ?, updated_at = ? WHERE session_id = ?",
                (session.model_dump_json(), session.updated_at.isoformat(), session_id),
            )
            await db.commit()
