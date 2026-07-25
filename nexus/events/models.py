"""Event models for the Nexus Agent Framework."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4, UUID

from pydantic import BaseModel, Field


class NexusEventType(str, Enum):
    """Types of events emitted by the framework."""
    # Agent lifecycle
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_ERROR = "agent.error"
    
    # Turn events
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_ERROR = "turn.error"
    
    # Tool events
    TOOL_CALL_STARTED = "tool_call.started"
    TOOL_CALL_COMPLETED = "tool_call.completed"
    TOOL_CALL_ERROR = "tool_call.error"
    
    # RCS events
    RCS_TC_SUMMARIZED = "rcs.tc_summarized"
    RCS_CONTEXT_BUILT = "rcs.context_built"
    RCS_COMPACTOR_TRIGGERED = "rcs.compactor_triggered"
    RCS_COMPACTOR_COMPLETED = "rcs.compactor_completed"
    RCS_CROSS_SESSION_TC_REFERENCE = "rcs.cross_session_tc_reference"
    
    # Memory events
    ENTITY_EXTRACTED = "memory.entity_extracted"

    # Context summary events
    CONTEXT_SUMMARIZED = "context.summarized"
    
    # Human-in-loop
    HUMAN_IN_LOOP_REQUESTED = "human_in_loop.requested"
    HUMAN_IN_LOOP_RESPONSE = "human_in_loop.response"
    
    # LLM events
    LLM_CALL_STARTED = "llm.call_started"
    LLM_CALL_COMPLETED = "llm.call_completed"
    LLM_CALL_ERROR = "llm.call_error"
    LLM_STREAM_CHUNK = "llm.stream.chunk"
    
    # Session events
    SESSION_CREATED = "session.created"
    SESSION_LOADED = "session.loaded"
    SESSION_SAVED = "session.saved"
    
    # Multi-agent
    AGENT_GROUP_STARTED = "agent_group.started"
    AGENT_GROUP_COMPLETED = "agent_group.completed"
    AGENT_HANDOFF = "agent.handoff"

    # Realtime / voice
    REALTIME_SESSION_STARTED = "realtime.session_started"
    REALTIME_SESSION_ENDED = "realtime.session_ended"
    REALTIME_TRANSCRIBED = "realtime.transcribed"
    REALTIME_BARGE_IN = "realtime.barge_in"
    REALTIME_RESPONSE_COMPLETED = "realtime.response_completed"
    REALTIME_ERROR = "realtime.error"
    REALTIME_RECONNECT = "realtime.reconnect"


class NexusEvent(BaseModel):
    """Base event model for all framework events."""
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: NexusEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    turn_index: Optional[int] = None
    data: dict[str, Any] = Field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert event to dictionary."""
        return self.model_dump()


class AgentStartedEvent(NexusEvent):
    """Emitted when an agent run starts."""
    
    event_type: NexusEventType = NexusEventType.AGENT_STARTED
    agent_name: str
    session_id: str
    user_message: Optional[str] = None


class AgentCompletedEvent(NexusEvent):
    """Emitted when an agent run completes."""
    
    event_type: NexusEventType = NexusEventType.AGENT_COMPLETED
    turns_used: int
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tokens_saved_by_rcs: int = 0
    cumulative_tokens_saved_by_rcs: int = 0


class AgentErrorEvent(NexusEvent):
    """Emitted when an agent run encounters an error."""
    
    event_type: NexusEventType = NexusEventType.AGENT_ERROR
    error: str
    traceback: Optional[str] = None


class TurnStartedEvent(NexusEvent):
    """Emitted when a new turn starts."""
    
    event_type: NexusEventType = NexusEventType.TURN_STARTED
    turn_index: int
    user_message: Optional[str] = None


class TurnCompletedEvent(NexusEvent):
    """Emitted when a turn completes."""
    
    event_type: NexusEventType = NexusEventType.TURN_COMPLETED
    turn_index: int
    tool_calls_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_saved: int = 0
    recurring_savings: int = 0
    duration_ms: int = 0


class ToolCallStartedEvent(NexusEvent):
    """Emitted when a tool call starts."""
    
    event_type: NexusEventType = NexusEventType.TOOL_CALL_STARTED
    tool_name: str
    tool_args: Optional[dict] = None


class ToolCallCompletedEvent(NexusEvent):
    """Emitted when a tool call completes."""
    
    event_type: NexusEventType = NexusEventType.TOOL_CALL_COMPLETED
    tool_name: str
    tool_output_length: int = 0
    duration_ms: int = 0


class ToolCallErrorEvent(NexusEvent):
    """Emitted when a tool call errors."""
    
    event_type: NexusEventType = NexusEventType.TOOL_CALL_ERROR
    tool_name: str
    error: str


class RCSContextBuiltEvent(NexusEvent):
    """Emitted when the context window is built."""
    
    event_type: NexusEventType = NexusEventType.RCS_CONTEXT_BUILT
    context_tokens: int = 0
    turns_in_context: int = 0
    tc_tags_count: int = 0
    tc_summarized_count: int = 0


class RCSTCSummarizedEvent(NexusEvent):
    """Emitted when a tool call result is summarized."""
    
    event_type: NexusEventType = NexusEventType.RCS_TC_SUMMARIZED
    tc_id: str
    tokens_raw: int = 0
    tokens_summarized: int = 0
    tokens_saved: int = 0


class RCSCompactorCompletedEvent(NexusEvent):
    """Emitted when the fallback ServerCompactor finishes compacting TCs."""

    event_type: NexusEventType = NexusEventType.RCS_COMPACTOR_COMPLETED
    tcs_compacted: list[str] = Field(default_factory=list)
    tokens_saved: int = 0


class LLMCallStartedEvent(NexusEvent):
    """Emitted when an LLM API call starts."""
    
    event_type: NexusEventType = NexusEventType.LLM_CALL_STARTED
    provider: str
    model: str
    messages_count: int = 0


class LLMCallCompletedEvent(NexusEvent):
    """Emitted when an LLM API call completes."""
    
    event_type: NexusEventType = NexusEventType.LLM_CALL_COMPLETED
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int = 0


class LLMCallErrorEvent(NexusEvent):
    """Emitted when an LLM API call errors."""
    
    event_type: NexusEventType = NexusEventType.LLM_CALL_ERROR
    provider: str
    error: str


class LLMStreamChunkEvent(NexusEvent):
    """Emitted for each LLM streaming chunk during a streaming call."""

    event_type: NexusEventType = NexusEventType.LLM_STREAM_CHUNK
    provider: str
    model: str
    turn_index: int
    content_delta: Optional[str] = None
    has_tool_call_delta: bool = False


class EventEmitted(NexusEvent):
    """Generic event wrapper for custom events."""
    
    event_type: NexusEventType = NexusEventType.AGENT_COMPLETED  # placeholder
    
    def __init__(self, event_type: NexusEventType, **kwargs: Any):
        super().__init__(event_type=event_type, data=kwargs)


ALL_EVENT_TYPES = list(NexusEventType)
