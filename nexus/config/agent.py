"""Agent configuration models."""

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from nexus.config.defaults import DEFAULT_SYSTEM_TEMPLATE
from nexus.config.llm import LLMProviderConfig
from nexus.config.memory import SessionMemoryConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.config.storage import SessionStorageConfig


class AgentPersonaConfig(BaseModel):
    """Persona configuration for an agent.

    Defines the role, goal, and backstory that shape the agent's behavior.
    """

    role: str = Field(..., description="e.g., 'Senior Data Analyst'")
    goal: str = Field(..., description="Task-level goal statement")
    backstory: Optional[str] = Field(None, description="Optional enrichment context")
    system_prompt: Optional[str] = Field(None, description="Full system prompt override")
    system_prompt_template: str = Field(
        default=DEFAULT_SYSTEM_TEMPLATE,
        description="Jinja2 template for system prompt",
    )


class TurnConfig(BaseModel):
    """Configuration for agent turn behavior."""

    max_turns: int = Field(default=10, ge=1, description="Max agentic loop iterations")
    max_tool_calls_per_turn: int = Field(
        default=5, ge=0, description="Guard against tool call storms (0 disables)"
    )
    stop_on_empty_tool_calls: bool = Field(
        default=True, description="Stop if LLM returns no tool calls"
    )
    stop_sequences: list[str] = Field(
        default_factory=list, description="Sequences that stop the agent"
    )
    stop_on_result_type: bool = Field(
        default=True, description="Stop when structured result is obtained"
    )
    human_in_loop_after_turns: Optional[int] = Field(
        None, ge=1, description="Pause for human input after this many turns"
    )
    turn_timeout_seconds: int = Field(
        default=300, ge=1, description="Per-turn timeout in seconds"
    )


class AgentConfig(BaseModel):
    """Complete configuration for a single agent.

    All configuration is passed explicitly - no global state or env vars.
    """

    name: str = Field(..., description="Unique agent identifier")
    llm: LLMProviderConfig = Field(..., description="LLM provider configuration")
    persona: AgentPersonaConfig = Field(
        default_factory=lambda: AgentPersonaConfig(role="Assistant", goal="Help the user"),
        description="Agent persona",
    )
    turns: TurnConfig = Field(
        default_factory=TurnConfig, description="Turn behavior configuration"
    )
    rcs: RuntimeContextSummarizerConfig = Field(
        default_factory=RuntimeContextSummarizerConfig,
        description="Runtime Context Summarization configuration",
    )
    session_memory: SessionMemoryConfig = Field(
        default_factory=SessionMemoryConfig,
        description="Per-session memory configuration (entity, working, cross-session promotion)",
    )
    storage: Optional[SessionStorageConfig] = Field(
        None, description="Session storage configuration"
    )
    tool_plugins: list[str] = Field(
        default_factory=list, description="Namespaces of tools to register"
    )
    result_type: Optional[type] = Field(
        None, description="Pydantic model for structured output"
    )
    trace_enabled: bool = Field(default=False, description="Enable observability tracing")
    trace_sink: Literal["stdout", "otel"] = Field(default="stdout", description="Observability trace target")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary metadata for this agent"
    )

    model_config = {"arbitrary_types_allowed": True}


class AgentGroupConfig(BaseModel):
    """Configuration for an agent group (composable black-box unit).

    Groups can contain individual agents or nested groups recursively.
    """

    name: str = Field(..., description="Human-readable group name")
    description: Optional[str] = Field(None, description="Group description")
    pattern: Literal["supervisor", "pipeline", "parallel", "swarm"] = Field(
        default="supervisor",
        description="Internal orchestration pattern",
    )
    members: list["MemberConfig"] = Field(
        default_factory=list,
        description="Recursive list of agents or nested groups",
    )
    max_turns: int = Field(
        default=20, ge=1, description="Total turns across all internal agents"
    )
    aggregation_strategy: Literal[
        "concat", "first_complete", "vote", "supervisor"
    ] = Field(
        default="supervisor",
        description="How to combine member results",
    )
    session_id_prefix: str = Field(
        default="", description="Prefix for member session IDs"
    )
    rcs: RuntimeContextSummarizerConfig = Field(
        default_factory=RuntimeContextSummarizerConfig,
        description="RCS configuration for group sessions",
    )

    model_config = {"arbitrary_types_allowed": True}


MemberConfig = Union[AgentConfig, AgentGroupConfig]

# Forward reference resolution for recursive type
AgentGroupConfig.model_rebuild()

# Resolve SessionMemoryConfig.curator_agent forward reference now that AgentConfig exists.
# model_rebuild() captures this module's namespace (which includes AgentConfig).
SessionMemoryConfig.model_rebuild()

