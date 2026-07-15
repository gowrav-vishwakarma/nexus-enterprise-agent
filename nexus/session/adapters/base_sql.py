"""Base SQL storage adapter — shared FOR UPDATE locking + codec plumbing.

Subclass this when your Postgres/SQLite table layout differs from Nexus
defaults (e.g. AITalk's ``AiTalkChats`` with ``chatJson``). Implement the
abstract mapping methods; ``append_turn`` / ``update_tc_summary`` come free.
"""

from __future__ import annotations

import json
import logging
from abc import abstractmethod
from datetime import datetime
from typing import Any, Optional

from nexus.session.adapters.base import StorageAdapter
from nexus.session.codec import DefaultSessionCodec, SessionCodec
from nexus.session.models import AgentSession, TurnRecord
from nexus.session.scope import SessionScope

logger = logging.getLogger(__name__)


class BaseSQLStorageAdapter(StorageAdapter):
    """Skeleton for custom SQL session tables.

    Subclasses provide connection + SQL mapping. This base handles:
    - SessionCodec serialization
    - Row lock → mutate → rewrite for ``append_turn`` / ``update_tc_summary``
    """

    def __init__(self, *, codec: Optional[SessionCodec] = None):
        self._codec: SessionCodec = codec or DefaultSessionCodec()

    # ── subclass hooks ──────────────────────────────────────────────────────

    @abstractmethod
    def table(self) -> str:
        """Qualified table name, e.g. ``ankpal.\"AiTalkChats\"``."""
        ...

    def json_column(self) -> str:
        """Column that holds the session JSON blob."""
        return "data"

    def id_column(self) -> str:
        """Primary session id column."""
        return "session_id"

    @abstractmethod
    def row_columns(self, session: AgentSession) -> dict[str, Any]:
        """Side columns to upsert alongside the JSON blob (no JSON col)."""
        ...

    @abstractmethod
    def scope_where(
        self, scope: Optional[SessionScope]
    ) -> tuple[str, list[Any]]:
        """Return ``(sql_fragment, params)`` for a WHERE clause (no leading AND/WHERE)."""
        ...

    @abstractmethod
    async def _fetch_one(
        self, sql: str, params: list[Any]
    ) -> Optional[dict[str, Any]]:
        """Run a SELECT and return one row as a dict, or None."""
        ...

    @abstractmethod
    async def _fetch_all(
        self, sql: str, params: list[Any]
    ) -> list[dict[str, Any]]:
        """Run a SELECT and return all rows as dicts."""
        ...

    @abstractmethod
    async def _execute(self, sql: str, params: list[Any]) -> None:
        """Run an INSERT/UPDATE/DELETE."""
        ...

    @abstractmethod
    async def _execute_in_transaction(
        self, work
    ) -> Any:
        """Run ``await work(conn)`` inside a transaction. ``work`` receives a
        connection that supports ``fetch_one_for_update`` / ``execute``."""
        ...

    # ── helpers ─────────────────────────────────────────────────────────────

    def _encode(self, session: AgentSession) -> Any:
        return self._codec.dumps(session)

    def _decode(self, data: Any) -> AgentSession:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        return self._codec.loads(data)

    def _json_param(self, session: AgentSession) -> Any:
        """Default: JSON string. Override for driver-native JSON types."""
        return json.dumps(self._encode(session), default=str)

    # ── StorageAdapter ──────────────────────────────────────────────────────

    async def save_session(self, session: AgentSession) -> None:
        session.update_timestamp()
        cols = self.row_columns(session)
        cols[self.json_column()] = self._json_param(session)
        col_names = list(cols.keys())
        placeholders = ", ".join(["%s"] * len(col_names))
        assignments = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in col_names if c != self.id_column()
        )
        sql = (
            f'INSERT INTO {self.table()} ({", ".join(col_names)}) '
            f"VALUES ({placeholders}) "
            f"ON CONFLICT ({self.id_column()}) DO UPDATE SET {assignments}"
        )
        # Subclasses with composite PKs should override save_session entirely.
        await self._execute(sql, list(cols.values()))

    async def load_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> Optional[AgentSession]:
        where, params = self.scope_where(scope)
        sql = (
            f"SELECT {self.json_column()} FROM {self.table()} "
            f"WHERE {self.id_column()} = %s"
        )
        params = [session_id, *params]
        if where:
            sql += f" AND {where}"
        row = await self._fetch_one(sql, params)
        if not row:
            return None
        session = self._decode(row[self.json_column()])
        if scope and not scope.matches_session(session):
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
        where, params = self.scope_where(scope)
        clauses = [where] if where else []
        if agent_id:
            # agent_id may only live inside JSON — subclasses can override
            clauses.append("TRUE")  # placeholder; filter post-load
        sql = f"SELECT {self.json_column()} FROM {self.table()}"
        if clauses:
            sql += " WHERE " + " AND ".join(c for c in clauses if c and c != "TRUE")
            if not any(c and c != "TRUE" for c in clauses):
                sql = f"SELECT {self.json_column()} FROM {self.table()}"
        sql += f" LIMIT %s OFFSET %s"
        params = [*params, limit, offset]
        rows = await self._fetch_all(sql, params)
        sessions = [self._decode(r[self.json_column()]) for r in rows]
        if agent_id:
            sessions = [s for s in sessions if s.agent_id == agent_id]
        if scope:
            sessions = [s for s in sessions if scope.matches_session(s)]
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        scope: Optional[SessionScope] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        where, params = self.scope_where(scope)
        sql = (
            f"SELECT {self.json_column()} FROM {self.table()} "
            f"WHERE {self.id_column()} LIKE %s"
        )
        params = [f"{session_id_prefix}%", *params]
        if where:
            sql += f" AND {where}"
        rows = await self._fetch_all(sql, params)
        excluded = exclude_session_ids or set()
        sessions = []
        for r in rows:
            session = self._decode(r[self.json_column()])
            if session.session_id in excluded:
                continue
            if scope and not scope.matches_session(session):
                continue
            sessions.append(session)
        sessions.sort(key=lambda s: s.created_at)
        return sessions

    async def delete_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        where, params = self.scope_where(scope)
        sql = f"DELETE FROM {self.table()} WHERE {self.id_column()} = %s"
        params = [session_id, *params]
        if where:
            sql += f" AND {where}"
        await self._execute(sql, params)

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        async def _work(tx):
            session = await self._lock_and_load(tx, session_id, scope)
            if session is None:
                return
            session.turns.append(turn)
            session.updated_at = datetime.now()
            await self._write_locked(tx, session)

        await self._execute_in_transaction(_work)

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        async def _work(tx):
            session = await self._lock_and_load(tx, session_id, scope)
            if session is None:
                return
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.tc_id == tc_id:
                        tc.summarized_response = summarized_response
                        tc.summarized_by_turn = summarized_by_turn
                        if summarized_response == "[]":
                            tc.is_dropped = True
                        session.updated_at = datetime.now()
                        await self._write_locked(tx, session)
                        return

        await self._execute_in_transaction(_work)

    async def _lock_and_load(
        self, tx: Any, session_id: str, scope: Optional[SessionScope]
    ) -> Optional[AgentSession]:
        where, params = self.scope_where(scope)
        sql = (
            f"SELECT {self.json_column()} FROM {self.table()} "
            f"WHERE {self.id_column()} = %s"
        )
        params = [session_id, *params]
        if where:
            sql += f" AND {where}"
        sql += " FOR UPDATE"
        row = await tx.fetch_one(sql, params)
        if not row:
            return None
        return self._decode(row[self.json_column()])

    async def _write_locked(self, tx: Any, session: AgentSession) -> None:
        cols = self.row_columns(session)
        cols[self.json_column()] = self._json_param(session)
        sets = ", ".join(f"{c} = %s" for c in cols)
        sql = (
            f"UPDATE {self.table()} SET {sets} "
            f"WHERE {self.id_column()} = %s"
        )
        await tx.execute(sql, [*cols.values(), session.session_id])
