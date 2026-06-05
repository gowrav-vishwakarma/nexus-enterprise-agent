"""Base storage adapter interface for the Nexus Agent Framework."""

from abc import ABC, abstractmethod
from typing import Optional

from nexus.session.models import AgentSession, TurnRecord


class StorageAdapter(ABC):
    """Abstract base class for session storage backends."""

    @abstractmethod
    async def save_session(self, session: AgentSession) -> None:
        """Save or update a complete session."""
        ...

    @abstractmethod
    async def load_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentSession]:
        """Load a session by ID."""
        ...

    @abstractmethod
    async def list_sessions(
        self,
        agent_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        """List sessions with optional filters."""
        ...

    @abstractmethod
    async def delete_session(
        self,
        session_id: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Delete a session."""
        ...

    @abstractmethod
    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Atomically append a turn to a session."""
        ...

    @abstractmethod
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
        """Update a tool call record's summary field."""
        ...
