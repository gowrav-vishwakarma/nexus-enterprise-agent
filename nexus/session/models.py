"""Session data models for the Nexus Agent Framework."""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class ContextUpdate(BaseModel):
    """A context compression update from the LLM."""
    tc_id: str = Field(..., description="Tool call ID, e.g. 'TC1'")
    summary: str = Field(..., description="Compressed summary of the tool result")

    def is_empty_sentinel(self) -> bool:
        """Check if this is an empty sentinel (drop from context)."""
        return self.summary == "[]"


class ToolCallRecord(BaseModel):
    """Record of a single tool call execution."""
    tc_id: str = Field(default_factory=lambda: str(uuid4()))
    tc_index: int = Field(..., description="Sequential index in session")
    tool_name: str = Field(..., description="Name of the tool called")
    tool_plugin: str = Field(default="", description="Plugin namespace")
    tool_input: dict = Field(default_factory=dict, description="Tool arguments (without _context_updates)")
    raw_response: str = Field(..., description="Original tool output")
    summarized_response: Optional[str] = Field(
        None,
        description="Summarized by LLM via _context_updates. None=not yet, '[]'=dropped",
    )
    summarized_by_turn: Optional[int] = Field(None, description="Turn that summarized this TC")
    tokens_raw: int = Field(default=0, description="Token count of raw response")
    tokens_summarized: Optional[int] = Field(None, description="Token count after summary")
    timestamp: datetime = Field(default_factory=datetime.now)
    is_dropped: bool = Field(default=False, description="True if summary is empty sentinel")


class TurnRecord(BaseModel):
    """Record of a single agent turn."""
    turn_index: int = Field(..., description="Turn number (0-based)")
    user_message: Optional[str] = Field(None, description="User input for this turn")
    llm_messages: list[dict] = Field(default_factory=list, description="Raw LLM message dicts")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="Tool calls in this turn")
    context_updates_received: list[dict] = Field(
        default_factory=list,
        description="Raw _context_updates from LLM this turn",
    )
    total_tokens_in: int = Field(default=0, description="Tokens sent to LLM")
    total_tokens_out: int = Field(default=0, description="Tokens received from LLM")
    tokens_saved_this_turn: int = Field(default=0, description="Tokens removed via _context_updates")
    media_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional media info for voice/AV/channel turns (modality, audio refs, transcript timing)",
    )
    duration_ms: int = Field(default=0, description="Turn duration in milliseconds")
    timestamp: datetime = Field(default_factory=datetime.now)
    status: str = Field(
        default="completed",
        description="Turn status: completed, error, interrupted, max_turns_reached",
    )
    error: Optional[str] = Field(None, description="Error message if failed")


class AgentSession(BaseModel):
    """Complete agent session with turns and memory."""
    session_id: str = Field(..., description="Unique session identifier")
    agent_id: str = Field(..., description="Agent that owns this session")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for multi-tenancy")
    user_id: Optional[str] = Field(None, description="User ID")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    turns: list[TurnRecord] = Field(default_factory=list)
    tc_counter: int = Field(default=0, description="Global TC index counter")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    summary_text: str = Field(default="", description="Rolling summary of folded turns")
    summary_through_turn: int = Field(
        default=-1,
        description="Last turn index folded into summary_text",
    )
    is_active: bool = Field(default=True, description="Whether session is still active")
    total_tokens_saved_by_rcs: int = Field(default=0, description="Cumulative RCS savings")

    @property
    def turn_count(self) -> int:
        """Number of turns in this session."""
        return len(self.turns)

    def next_tc_index(self) -> int:
        """Get and increment the next TC index."""
        idx = self.tc_counter
        self.tc_counter += 1
        return idx

    def update_timestamp(self):
        """Update the session updated_at timestamp."""
        self.updated_at = datetime.now()

    def find_tc(self, tc_id: str) -> Optional[ToolCallRecord]:
        """Find a tool call record by its TC ID."""
        for turn in self.turns:
            for tc in turn.tool_calls:
                if tc.tc_id == tc_id:
                    return tc
        return None

