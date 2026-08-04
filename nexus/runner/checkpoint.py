"""Run checkpointing for crash recovery."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nexus.session.models import AgentSession, PendingInteraction


class RunCheckpoint(BaseModel):
    """Mid-run state persisted for resume after crash."""

    session_id: str
    turn_index: int
    pending_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    pending_interactions: list[dict[str, Any]] = Field(default_factory=list)
    state: dict[str, Any] = Field(default_factory=dict)
    stream_seq: int = 0


def checkpoint_from_session(session: AgentSession, *, turn_index: int, stream_seq: int = 0) -> RunCheckpoint:
    return RunCheckpoint(
        session_id=session.session_id,
        turn_index=turn_index,
        pending_interactions=[p.model_dump(mode="json") for p in session.pending_interactions],
        state=dict(session.state or {}),
        stream_seq=stream_seq,
    )


def apply_checkpoint(session: AgentSession, checkpoint: RunCheckpoint) -> None:
    session.state = dict(checkpoint.state)
    session.pending_interactions = [
        PendingInteraction.model_validate(p) for p in checkpoint.pending_interactions
    ]
