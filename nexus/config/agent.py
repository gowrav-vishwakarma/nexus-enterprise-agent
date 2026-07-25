"""Agent configuration models."""

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from nexus.config.defaults import DEFAULT_SYSTEM_TEMPLATE
from nexus.config.llm import LLMProviderConfig
from nexus.config.context_summary import ContextSummaryConfig
from nexus.config.memory import MemoryConfig
from nexus.config.rcs import RuntimeContextSummarizerConfig
from nexus.config.storage import SessionStorageConfig
from nexus.skills.config import SkillsConfig


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
    prompt_args: dict[str, Any] = Field(
        default_factory=dict,
        description="Extra Jinja variables from orchestration YAML (e.g. domain)",
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
    memory: MemoryConfig = Field(
        default_factory=MemoryConfig,
        description="Cross-session user memory configuration (curator + injection)",
    )
    context_summary: ContextSummaryConfig = Field(
        default_factory=ContextSummaryConfig,
        description="Rolling conversation summary when context fill exceeds summarize_on",
    )
    storage: Optional[SessionStorageConfig] = Field(
        None, description="Session storage configuration"
    )
    tool_plugins: list[str] = Field(
        default_factory=list, description="Namespaces of tools to register"
    )
    toolset: Optional[Union[str, list[str]]] = Field(
        default=None,
        description=(
            "Toolset name (or list of names) defined on the agent's tool "
            "registry. Resolved to the agent's tool allow-list at run time. "
            "None means no restriction (all registered tools are visible)."
        ),
    )
    skills: SkillsConfig = Field(
        default_factory=SkillsConfig,
        description="Agent skills configuration (agentskills.io compatible)",
    )
    result_type: Optional[type] = Field(
        None, description="Pydantic model for structured output"
    )
    trace_enabled: bool = Field(default=False, description="Enable observability tracing")
    trace_sink: Literal["stdout", "otel"] = Field(default="stdout", description="Observability trace target")
    stream_output: bool = Field(
        default=False,
        description="Default execution mode: stream AgentStreamEvents vs return blocking AgentRunResult",
    )
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
    supervisor: Optional[str] = Field(
        default=None,
        description="Member name that leads supervisor-pattern groups (default: name heuristic)",
    )
    persist_members: bool = Field(
        default=False,
        description="When False, member runs use is_subagent and skip durable chat persistence",
    )
    rcs: RuntimeContextSummarizerConfig = Field(
        default_factory=RuntimeContextSummarizerConfig,
        description="RCS configuration for group sessions",
    )
    stream_output: bool = Field(
        default=False,
        description="Default execution mode: stream AgentStreamEvents vs return blocking AgentGroupResult",
    )

    model_config = {"arbitrary_types_allowed": True}


MemberConfig = Union[AgentConfig, AgentGroupConfig]

# Forward reference resolution for recursive type
AgentGroupConfig.model_rebuild()

# Resolve MemoryConfig.curator_agent forward reference now that AgentConfig exists.
MemoryConfig.model_rebuild()

