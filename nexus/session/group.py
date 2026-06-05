"""Data models for aggregated session group views."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from nexus.session.models import TurnRecord


class SessionNode(BaseModel):
    """One session in a group, optionally with nested sub-agent children."""

    session_id: str
    agent_id: str
    member_name: Optional[str] = None
    turns: list[TurnRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    children: list[SessionNode] = Field(
        default_factory=list,
        description="Nested sub-agent runs in execution order",
    )


class SessionGroupView(BaseModel):
    """Aggregated view of a root chat session and its sub-agent sessions."""

    root_session_id: str
    session_id_prefix: str = ""
    pattern: Literal["single", "pipeline", "supervisor", "unknown"] = "unknown"
    sessions: list[SessionNode] = Field(
        default_factory=list,
        description="Top-level sessions in execution order",
    )
