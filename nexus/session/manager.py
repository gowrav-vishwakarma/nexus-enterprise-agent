"""Session manager for the Nexus Agent Framework."""

import logging
from datetime import datetime
from typing import Any, Optional

from nexus.session.models import AgentSession, TurnRecord
from nexus.session.adapters.base import StorageAdapter
from nexus.session.adapters.memory import MemoryStorageAdapter
from nexus.config.storage import SessionStorageConfig

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages agent sessions with persistent storage."""

    def __init__(self, storage_adapter: Optional[StorageAdapter] = None):
        self._adapter = storage_adapter or MemoryStorageAdapter()

    @classmethod
    def from_config(cls, config: Optional[SessionStorageConfig] = None) -> "SessionManager":
        """Create a SessionManager from a SessionStorageConfig."""
        if config is None:
            return cls()

        adapter = cls._create_adapter_from_config(config)
        return cls(storage_adapter=adapter)

    @staticmethod
    def _create_adapter_from_config(config: SessionStorageConfig) -> StorageAdapter:
        """Create a storage adapter based on configuration."""
        adapter_type = config.adapter or "memory"
        adapter_config = config.adapter_config or {}

        if adapter_type == "memory":
            from nexus.session.adapters.memory import MemoryStorageAdapter
            return MemoryStorageAdapter(**adapter_config)
        elif adapter_type == "file":
            from nexus.session.adapters.file import FileStorageAdapter
            return FileStorageAdapter(**adapter_config)
        elif adapter_type == "sqlite":
            from nexus.session.adapters.sqlite import SQLiteStorageAdapter
            return SQLiteStorageAdapter(**adapter_config)
        elif adapter_type == "postgresql":
            logger.warning("PostgreSQL adapter not yet implemented, falling back to sqlite")
            from nexus.session.adapters.sqlite import SQLiteStorageAdapter
            return SQLiteStorageAdapter(db_path="./postgresql_fallback.db")
        elif adapter_type == "redis":
            logger.warning("Redis adapter not yet implemented, falling back to memory")
            return MemoryStorageAdapter()
        else:
            logger.warning("Unknown adapter type '%s', falling back to memory", adapter_type)
            return MemoryStorageAdapter()

    async def create_session(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AgentSession:
        """Create a new agent session."""
        if session_id is None:
            import uuid
            session_id = str(uuid.uuid4())

        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            metadata=metadata or {},
        )

        await self._adapter.save_session(session)
        return session

    async def load_session(self, session_id: str) -> Optional[AgentSession]:
        """Load a session by ID."""
        return await self._adapter.load_session(session_id)

    async def save_session(self, session: AgentSession) -> None:
        """Save a session."""
        session.update_timestamp()
        await self._adapter.save_session(session)

    async def append_turn(self, session_id: str, turn: TurnRecord) -> None:
        """Append a turn to an existing session."""
        await self._adapter.append_turn(session_id, turn)

    async def update_tc_summary(
        self,
        session_id: str,
        tc_id: str,
        summarized_response: str,
        summarized_by_turn: int,
    ) -> None:
        """Update a tool call record's summary."""
        await self._adapter.update_tc_summary(
            session_id=session_id,
            tc_id=tc_id,
            summarized_response=summarized_response,
            summarized_by_turn=summarized_by_turn,
        )

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        await self._adapter.delete_session(session_id)
        return True

    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        """List sessions with optional filters."""
        return await self._adapter.list_sessions(
            agent_id=agent_id,
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

    async def deactivate_session(self, session_id: str) -> bool:
        """Deactivate a session without deleting it."""
        session = await self.load_session(session_id)
        if session:
            session.is_active = False
            await self.save_session(session)
            return True
        return False
