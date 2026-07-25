"""Turn-boundary hooks for deterministic control of the agent loop."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from nexus.session.models import AgentSession


class TurnDecision(BaseModel):
    """Instruction returned by ``on_turn_end`` to influence the next loop step."""

    action: Literal["continue", "stop", "inject"] = Field(
        default="continue",
        description="continue: default loop; stop: end run; inject: next user_message",
    )
    message: Optional[str] = Field(
        default=None,
        description="User message for the next turn when action is inject",
    )


class TurnContext(BaseModel):
    """Context passed to ``on_turn_end`` after a turn is persisted."""

    model_config = {"arbitrary_types_allowed": True}

    session: AgentSession
    turn_index: int = Field(..., description="Session turn index just completed")
    run_turn_index: int = Field(..., description="0-based index within this run() call")
    tool_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tool name and raw response strings from this turn",
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Mutable durable state (same dict as run_context.state)",
    )
    final_response: Optional[str] = Field(
        default=None,
        description="Assistant text if the turn ended without more tool calls",
    )
