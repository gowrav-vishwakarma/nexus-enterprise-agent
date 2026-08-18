"""Cross-session memory configuration models."""

from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, Field

from nexus.config.llm import LLMProviderConfig

if TYPE_CHECKING:
    from nexus.config.agent import AgentConfig


class MemoryStoreConfig(BaseModel):
    """One named memory store (e.g. user profile vs agent notes)."""

    name: str = Field(..., description="Store name, e.g. user or memory")
    description: str = Field(default="", description="Shown in prompts / tools")
    inject: Literal["always", "on_recall"] = Field(
        default="always",
        description="always = inject into system prompt; on_recall = tool search only",
    )
    char_budget: int = Field(
        default=0,
        ge=0,
        description="Soft char budget for always-injected stores (0 = no budget)",
    )
    max_entries: int = Field(default=100, ge=1, description="Max keys in this store")


class MemoryConfig(BaseModel):
    """Cross-session user memory configuration.

    Memory is written by tools and/or an optional memory curator. Reading is
    automatic for stores with inject=always.
    """

    enabled: bool = Field(
        default=False,
        description="Master gate. If False the curator is a no-op and memory is not injected",
    )
    expose_tools: bool = Field(
        default=True,
        description="Auto-register the memory tool plugin when enabled",
    )
    namespace: str = Field(
        default="",
        description="Isolation key for facts (empty = agent name)",
    )
    stores: list[MemoryStoreConfig] = Field(
        default_factory=list,
        description="Named stores; empty = single default store",
    )
    max_entities: int = Field(
        default=100,
        ge=1,
        description="Hard cap on stored entities (oldest dropped beyond cap)",
    )

    extract_after_each_turn: bool = Field(
        default=True,
        description="Run the curator after each completed turn",
    )
    extraction_interval: int = Field(
        default=0,
        ge=0,
        description="Optional: run every N turns (0 = use extract_after_each_turn only)",
    )
    extract_at_end: bool = Field(
        default=False,
        description="Run once more after run() finishes",
    )
    inject_into_prompt: bool = Field(
        default=True,
        description="Inject stored user facts into the system prompt",
    )
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
        description="Advanced: a full AgentConfig used as the curator",
    )
    max_conversation_chars: int = Field(
        default=6000,
        ge=200,
        description="Max characters of recent conversation fed to the curator",
    )
    provider: Optional[str] = Field(
        default=None,
        description=(
            "Optional memory provider id: builtin_semantic, builtin_kv, mem0, honcho, "
            "or custom_class. None = use CrossSessionMemoryStore directly (current behaviour)"
        ),
    )
    provider_class: Optional[str] = Field(
        default=None,
        description="Dotted import path when provider is custom_class",
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Kwargs passed to the provider constructor",
    )
    require_approval: bool = Field(
        default=False,
        description=(
            "When True, curator writes pending facts; only approved facts are injected. "
            "Default False keeps immediate curator writes"
        ),
    )

    model_config = {"arbitrary_types_allowed": True}

    def get_curator_prompt(self) -> str:
        """Return the curator prompt, using the default if not overridden."""
        from nexus.config.defaults import DEFAULT_MEMORY_CURATOR_PROMPT

        return self.curator_prompt or DEFAULT_MEMORY_CURATOR_PROMPT
