"""Base storage adapter interface for the Nexus Agent Framework.

All session storage backends must implement ``list_sessions_by_prefix`` with
consistent semantics: return every session whose ``session_id`` starts with the
given prefix (after optional scope filtering). Sort by ``created_at`` ascending.
"""

from abc import ABC, abstractmethod
from typing import Optional

from nexus.session.models import AgentSession, TurnRecord
from nexus.session.scope import SessionScope


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
        scope: Optional[SessionScope] = None,
    ) -> Optional[AgentSession]:
        """Load a session by ID, optionally filtered by scope."""
        ...

    @abstractmethod
    async def list_sessions(
        self,
        *,
        agent_id: Optional[str] = None,
        scope: Optional[SessionScope] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentSession]:
        """List sessions with optional filters."""
        ...

    @abstractmethod
    async def list_sessions_by_prefix(
        self,
        session_id_prefix: str,
        *,
        scope: Optional[SessionScope] = None,
        exclude_session_ids: Optional[set[str]] = None,
    ) -> list[AgentSession]:
        """Return sessions whose session_id starts with session_id_prefix."""
        ...

    @abstractmethod
    async def delete_session(
        self,
        session_id: str,
        *,
        scope: Optional[SessionScope] = None,
    ) -> None:
        """Delete a session."""
        ...

    @abstractmethod
    async def append_turn(
        self,
        session_id: str,
        turn: TurnRecord,
        *,
        scope: Optional[SessionScope] = None,
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
        scope: Optional[SessionScope] = None,
    ) -> None:
        """Update a tool call record's summary field."""
        ...
