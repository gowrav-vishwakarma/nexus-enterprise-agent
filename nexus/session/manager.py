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
        adapter_config = dict(config.adapter_config or {})

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
            from nexus.session.adapters.postgresql import PostgreSQLStorageAdapter
            if "dsn" not in adapter_config:
                raise ValueError("postgresql adapter requires 'dsn' in adapter_config")
            return PostgreSQLStorageAdapter(**adapter_config)
        elif adapter_type == "redis":
            from nexus.session.adapters.redis import RedisStorageAdapter
            return RedisStorageAdapter(**adapter_config)
        elif adapter_type == "custom":
            if not config.custom_adapter_class:
                raise ValueError("custom adapter requires custom_adapter_class")
            from nexus.persistence.factory import load_custom_adapter
            return load_custom_adapter(config.custom_adapter_class, adapter_config)
        else:
            logger.warning("Unknown adapter type '%s', falling back to memory", adapter_type)
            from nexus.session.adapters.memory import MemoryStorageAdapter
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

    async def load_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        """Load a session by ID."""
        return await self._adapter.load_session(
            session_id, tenant_id=tenant_id, user_id=user_id
        )

    async def save_session(self, session: AgentSession) -> None:
        """Save a session."""
        session.update_timestamp()
        await self._adapter.save_session(session)

    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Append a turn to an existing session."""
        await self._adapter.append_turn(
            session_id, turn, tenant_id=tenant_id, user_id=user_id
        )

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
        """Update a tool call record's summary."""
        await self._adapter.update_tc_summary(
            session_id=session_id,
            tc_id=tc_id,
            summarized_response=summarized_response,
            summarized_by_turn=summarized_by_turn,
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def delete_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Delete a session."""
        await self._adapter.delete_session(
            session_id, tenant_id=tenant_id, user_id=user_id
        )
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

    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        """Return sessions whose session_id starts with session_id_prefix."""
        return await self._adapter.list_sessions_by_prefix(
            session_id_prefix,
            tenant_id=tenant_id,
            user_id=user_id,
            exclude_session_ids=exclude_session_ids,
        )

    async def load_session_group(
        self,
        root_session_id: str,
        *,
        session_id_prefix: str = "",
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        pattern: str = "auto",
        member_order: Optional[list[str]] = None,
        include_internal: bool = False,
    ):
        """Load and aggregate all sub-agent sessions for a root chat session id."""
        from nexus.session.aggregate import load_session_group

        return await load_session_group(
            self,
            root_session_id,
            session_id_prefix=session_id_prefix,
            tenant_id=tenant_id,
            user_id=user_id,
            pattern=pattern,  # type: ignore[arg-type]
            member_order=member_order,
            include_internal=include_internal,
        )

    async def deactivate_session(self, session_id: str) -> bool:
        """Deactivate a session without deleting it."""
        session = await self.load_session(session_id)
        if session:
            session.is_active = False
            await self.save_session(session)
            return True
        return False
