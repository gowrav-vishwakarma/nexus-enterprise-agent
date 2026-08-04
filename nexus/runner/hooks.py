"""Turn-boundary and lifecycle hooks for deterministic control of the agent loop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from nexus.session.models import AgentSession
from nexus.tools.context import RunContext


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


class ToolCallContext(BaseModel):
    """Context passed to before/after tool hooks."""

    model_config = {"arbitrary_types_allowed": True}

    session: AgentSession
    turn_index: int
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    run_context: RunContext
    tc_id: str = ""


class LLMCallContext(BaseModel):
    """Context passed to before_llm_call hooks."""

    model_config = {"arbitrary_types_allowed": True}

    session: AgentSession
    turn_index: int
    messages: list[dict[str, Any]]
    run_context: RunContext


HookResult = Optional[Union[TurnDecision, dict[str, Any], bool, str]]

OnTurnStart = Callable[[TurnContext, RunContext], Awaitable[None]]
OnTurnEnd = Callable[[TurnContext], Awaitable[Optional[TurnDecision]]]
BeforeToolCall = Callable[[ToolCallContext], Awaitable[Optional[dict[str, Any]]]]
AfterToolCall = Callable[[ToolCallContext, Any], Awaitable[None]]
BeforeLLMCall = Callable[[LLMCallContext], Awaitable[Optional[list[dict[str, Any]]]]]


class RunnerHooks(BaseModel):
    """Optional lifecycle hooks for AgentRunner."""

    model_config = {"arbitrary_types_allowed": True}

    on_turn_start: Optional[OnTurnStart] = None
    on_turn_end: Optional[OnTurnEnd] = None
    before_tool_call: Optional[BeforeToolCall] = None
    after_tool_call: Optional[AfterToolCall] = None
    before_llm_call: Optional[BeforeLLMCall] = None
