"""In-memory storage adapter for the Nexus Agent Framework."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from nexus.session.models import AgentSession, TurnRecord, ToolCallRecord
from nexus.session.adapters.base import StorageAdapter

logger = logging.getLogger(__name__)


class MemoryStorageAdapter(StorageAdapter):
    """In-memory storage using Python dict.
    
    Use case: Testing, short-lived tasks, unit tests.
    Thread-safety: asyncio.Lock per session_id
    """

    def __init__(self, max_sessions: int = 10000, ttl_seconds: Optional[int] = None):
        self._sessions: dict[str, AgentSession] = {}
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def _evict_if_needed(self):
        """LRU eviction if max sessions reached."""
        if len(self._sessions) > self._max_sessions:
            oldest_id = min(
                self._sessions.keys(),
                key=lambda sid: self._sessions[sid].updated_at,
            )
            logger.info("Evicting session %s (max sessions reached)", oldest_id)
            del self._sessions[oldest_id]

    async def save_session(self, session: AgentSession) -> None:
        async with self._get_lock(session.session_id):
            self._sessions[session.session_id] = session
            self._evict_if_needed()

    async def load_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        async with self._get_lock(session_id):
            session = self._sessions.get(session_id)
            if session and self._ttl_seconds:
                age = (datetime.now() - session.updated_at).total_seconds()
                if age > self._ttl_seconds:
                    del self._sessions[session_id]
                    return None
            return session

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        results = []
        for session in self._sessions.values():
            if agent_id and session.agent_id != agent_id:
                continue
            if tenant_id and session.tenant_id != tenant_id:
                continue
            if user_id and session.user_id != user_id:
                continue
            results.append(session)
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results[offset:offset + limit]

    async def delete_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        async with self._get_lock(session_id):
            self._sessions.pop(session_id, None)

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        async with self._get_lock(session_id):
            session = self._sessions.get(session_id)
            if session:
                session.turns.append(turn)
                session.updated_at = datetime.now()

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        async with self._get_lock(session_id):
            session = self._sessions.get(session_id)
            if session:
                for turn in session.turns:
                    for tc in turn.tool_calls:
                        if tc.tc_id == tc_id:
                            tc.summarized_response = summarized_response
                            tc.summarized_by_turn = summarized_by_turn
                            if summarized_response == "[]":
                                tc.is_dropped = True
                            session.updated_at = datetime.now()
                            return
