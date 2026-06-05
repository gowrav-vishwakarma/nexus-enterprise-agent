"""Cross-session memory configuration models."""

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from nexus.config.llm import LLMProviderConfig

if TYPE_CHECKING:
    from nexus.config.agent import AgentConfig


class MemoryConfig(BaseModel):
    """Cross-session user memory configuration.

    Memory is written by an optional "memory curator" - a separate, gated LLM call
    (or a full agent) that extracts durable facts from the conversation and merges
    them into the cross-session store. Reading is automatic: stored facts are
    injected into the system prompt unless ``inject_into_prompt`` is False.

    Within a single chat thread, context comes from ``session.turns`` and RCS
    summaries — not from this config.
    """

    enabled: bool = Field(
        default=False,
        description="Master gate. If False the curator is a no-op and memory is not injected",
    )
    namespace: str = Field(
        default="",
        description="Isolation key for facts (empty = agent name)",
    )
    max_entities: int = Field(
        default=100,
        ge=1,
        description="Hard cap on stored entities (oldest dropped beyond cap)",
    )

    # Triggers
    extract_after_each_turn: bool = Field(
        default=True,
        description="Run the curator after each completed turn (default behavior)",
    )
    extraction_interval: int = Field(
        default=0,
        ge=0,
        description=(
            "Optional: run every N turns instead of/in addition to each turn "
            "(0 = use extract_after_each_turn only)"
        ),
    )
    extract_at_end: bool = Field(
        default=False,
        description=(
            "Run once more after run() finishes (safety net; skipped if that turn "
            "was already curated)"
        ),
    )

    # Fetching / injection
    inject_into_prompt: bool = Field(
        default=True,
        description="Inject stored user facts into the system prompt",
    )

    # Curator (writer) configuration
    curator_llm: Optional[LLMProviderConfig] = Field(
        default=None,
        description="Dedicated LLM for the curator (falls back to the agent's main LLM)",
    )
    curator_prompt: str = Field(
        default="",
        description="Custom curator prompt (empty = DEFAULT_MEMORY_CURATOR_PROMPT)",
    )
    curator_agent: Optional["AgentConfig"] = Field(
        default=None,
        description="Advanced: a full AgentConfig used as the curator (own prompt/tools)",
    )

    max_conversation_chars: int = Field(
        default=6000,
        ge=200,
        description="Max characters of recent conversation fed to the curator",
    )

    model_config = {"arbitrary_types_allowed": True}

    def get_curator_prompt(self) -> str:
        """Return the curator prompt, using the default if not overridden."""
        from nexus.config.defaults import DEFAULT_MEMORY_CURATOR_PROMPT

        return self.curator_prompt or DEFAULT_MEMORY_CURATOR_PROMPT
