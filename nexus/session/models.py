"""Session data models for the Nexus Agent Framework."""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


TurnStatus = Literal[
    "completed",
    "error",
    "interrupted",
    "max_turns_reached",
    "paused",
    "security_block",
]


class ContextUpdate(BaseModel):
    """A context compression update from the LLM."""

    tc_id: str = Field(..., description="Tool call ID, e.g. 'TC1'")
    summary: str = Field(..., description="Compressed summary of the tool result")
    tokens_saved: int = Field(
        default=0,
        description="Tokens saved by this update (tokens_raw - tokens_summarized). "
        "Populated by the interceptor so callers (e.g. AgentRunner) use the same "
        "formula as session.total_tokens_saved_by_rcs.",
    )


class PendingInteraction(BaseModel):
    """A paused client-tool or elicitation waiting for an external result."""

    tc_id: str = Field(..., description="Nexus TC id, e.g. TC1")
    call_id: str = Field(default="", description="Provider tool_call id")
    tool_name: str = Field(..., description="Tool that was deferred")
    args: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["client_tool", "elicitation"] = "client_tool"
    created_at: datetime = Field(default_factory=datetime.now)


class ToolCallRecord(BaseModel):
    """Record of a single tool call execution."""

    tc_id: str = Field(default_factory=lambda: str(uuid4()))
    tc_index: int = Field(..., description="Sequential index in session")
    tool_name: str = Field(..., description="Name of the tool called")
    tool_plugin: str = Field(default="", description="Plugin namespace")
    call_id: str = Field(
        default="",
        description="Provider tool_call id — links assistant tool_call ↔ tool result",
    )
    tool_input: dict = Field(
        default_factory=dict,
        description="Tool arguments (without _context_updates)",
    )
    raw_response: str = Field(..., description="Original tool output")
    summarized_response: Optional[str] = Field(
        None,
        description="Summary of raw_response, set by the LLM via _context_updates or "
        "by the fallback compactor. None or empty means not summarized, so the raw "
        "response is used in context.",
    )
    summarized_by_turn: Optional[int] = Field(
        None, description="Turn that summarized this TC"
    )
    tokens_raw: int = Field(default=0, description="Token count of raw response")
    tokens_summarized: Optional[int] = Field(
        None, description="Token count after summary"
    )
    timestamp: datetime = Field(default_factory=datetime.now)


class TurnRecord(BaseModel):
    """Record of a single agent turn."""

    turn_index: int = Field(..., description="Turn number (0-based)")
    user_message: Optional[str] = Field(None, description="User input for this turn")
    llm_messages: list[dict] = Field(
        default_factory=list, description="Raw LLM message dicts"
    )
    reasoning: Optional[str] = Field(
        None,
        description="Reasoning/thinking text the model produced this turn. Kept "
        "outside llm_messages because those dicts are replayed verbatim into the "
        "provider request, which would reject an unknown key.",
    )
    tool_calls: list[ToolCallRecord] = Field(
        default_factory=list, description="Tool calls in this turn"
    )
    context_updates_received: list[dict] = Field(
        default_factory=list,
        description="Raw _context_updates from LLM this turn",
    )
    total_tokens_in: int = Field(default=0, description="Tokens sent to LLM")
    total_tokens_out: int = Field(default=0, description="Tokens received from LLM")
    tokens_saved_this_turn: int = Field(
        default=0, description="One-time tokens removed via _context_updates (at summarization moment)"
    )
    recurring_savings_this_turn: int = Field(
        default=0,
        description="Recurring input-token savings this turn: how many input tokens RCS saved "
        "by having summarized TCs in context instead of their raw versions. "
        "Accumulates into session.cumulative_input_tokens_saved_by_rcs."
    )
    media_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional media info for voice/AV/channel turns",
    )
    duration_ms: int = Field(default=0, description="Turn duration in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.now)
    status: TurnStatus = Field(
        default="completed",
        description="completed | error | interrupted | max_turns_reached | paused | security_block",
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class AgentSession(BaseModel):
    """Complete agent session with turns and product chat metadata."""

    session_id: str = Field(..., description="Unique session identifier")
    agent_id: str = Field(..., description="Agent that owns this session")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for multi-tenancy")
    company_id: Optional[str] = Field(
        None, description="Company within a tenant (multi-company products)"
    )
    user_id: Optional[str] = Field(None, description="User ID")
    user_name: Optional[str] = Field(None, description="Display name")
    title: str = Field(default="", description="Chat title (sidebar)")
    pinned: bool = Field(default=False, description="Pinned in the sidebar")
    attachment_ids: list[str] = Field(
        default_factory=list,
        description="Session-scoped staged attachment ids",
    )
    pending_interactions: list[PendingInteraction] = Field(
        default_factory=list,
        description="Client tools / elicitations waiting for resume",
    )
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Durable app state for this chat thread (checkpoint). Survives across runs.",
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    turns: list[TurnRecord] = Field(default_factory=list)
    tc_counter: int = Field(default=0, description="Global TC index counter")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata"
    )
    summary_text: str = Field(default="", description="Rolling summary of folded turns")
    summary_through_turn: int = Field(
        default=-1,
        description="Last turn index folded into summary_text",
    )
    is_active: bool = Field(default=True, description="Whether session is still active")
    total_tokens_saved_by_rcs: int = Field(
        default=0, description="One-time RCS compression savings (tokens_raw - tokens_summarized per TC at summarization moment)"
    )
    cumulative_input_tokens_saved_by_rcs: int = Field(
        default=0,
        description="Recurring input-token savings across all turns. A TC summarized in turn N "
        "saves input tokens in every subsequent turn that includes it; this counter "
        "accumulates those recurring savings, giving the true cost impact of RCS."
    )
    rcs_enabled: bool = Field(
        default=False,
        description="Whether RCS was enabled for this session. Set once at run start "
        "so the persisted chat JSON records whether RCS was active."
    )

    @computed_field
    @property
    def token_usage(self) -> dict[str, Any]:
        """Aggregate token-accounting block for this chat.

        Included verbatim in ``model_dump(mode="json")`` so the stored chat JSON
        blob carries pre-aggregated metrics that external readers (SQL, scripts,
        BI tools) can read directly without summing per-turn fields. Inside the
        app this recomputes on load, so it can never drift from the per-turn data.

        - ``total_tokens_in`` / ``total_tokens_out``: actual tokens sent/received,
          summed from turns (RCS already applied to inputs).
        - ``total_tokens_saved_by_rcs``: one-time RCS compression savings.
        - ``cumulative_input_tokens_saved_by_rcs``: recurring input-token savings.
        - ``rcs_enabled``: whether RCS was enabled for this chat.
        """
        return {
            "total_tokens_in": sum(t.total_tokens_in for t in self.turns),
            "total_tokens_out": sum(t.total_tokens_out for t in self.turns),
            "total_tokens_saved_by_rcs": self.total_tokens_saved_by_rcs,
            "cumulative_input_tokens_saved_by_rcs": self.cumulative_input_tokens_saved_by_rcs,
            "rcs_enabled": self.rcs_enabled,
        }


    @property
    def turn_count(self) -> int:
        """Number of turns in this session."""
        return len(self.turns)

    def next_tc_index(self) -> int:
        """Get and increment the next TC index."""
        idx = self.tc_counter
        self.tc_counter += 1
        return idx

    def update_timestamp(self) -> None:
        """Update the session updated_at timestamp."""
        self.updated_at = datetime.now()

    def find_tc(self, tc_id: str) -> Optional[ToolCallRecord]:
        """Find a tool call record by its TC ID."""
        for turn in self.turns:
            for tc in turn.tool_calls:
                if tc.tc_id == tc_id:
                    return tc
        return None

    def to_scope(self):
        """Build a SessionScope from this session's identity fields."""
        from nexus.session.scope import SessionScope

        return SessionScope(
            tenant_id=self.tenant_id,
            company_id=self.company_id,
            user_id=self.user_id,
        )
