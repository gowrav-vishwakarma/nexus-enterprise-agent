"""Runtime Context Summarization (RCS) configuration."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from nexus.config.llm import LLMProviderConfig


class ServerCompactorConfig(BaseModel):
    """Fallback compactor configuration.

    Only used when LLM-driven inline compression isn't enough.
    Makes a separate LLM call to summarize tagged TCs.
    """

    enabled: bool = Field(default=False, description="Enable fallback compactor")
    trigger_token_threshold: int = Field(default=10000, description="Trigger threshold in tokens")
    compact_oldest_n_tcs: int = Field(default=2, description="Number of oldest TCs to compact")
    compactor_llm: Optional[LLMProviderConfig] = Field(default=None, description="Custom LLM for compaction")
    max_tokens_per_summary: int = Field(
        default=100, ge=10, description="Max tokens per compacted summary"
    )
    prompt_template: str = Field(
        default="",
        description="Custom prompt for compaction (empty = use default)",
    )



class RuntimeContextSummarizerConfig(BaseModel):
    """Configuration for Runtime Context Summarization (RCS).

    Primary mechanism: LLM-driven inline compression via _context_updates.
    The agent summarizes its own tool results as part of normal tool calls.
    """

    enabled: bool = Field(
        default=False, description="Enable RCS (LLM-driven inline compression)"
    )

    # TC Tagging
    tc_tag_format: str = Field(
        default="[TC{n}]",
        description="Format of tag for unsummarized tool results",
    )
    tc_tag_include_tool_signature: bool = Field(
        default=True,
        description="Include tool name + args in tag, e.g., [TC1] web_search(query='...')",
    )

    # Context Updates Injection
    context_updates_param_name: str = Field(
        default="_context_updates",
        description="Parameter name injected into tool schemas",
    )
    context_updates_param_description: str = Field(
        default="",
        description="Description for the _context_updates param (empty = use default)",
    )
    empty_summary_sentinel: str = Field(
        default="[]",
        description="Sentinel value meaning 'this TC result is useless, drop it from context'",
    )

    # System Prompt Injection
    rcs_system_block: str = Field(
        default="",
        description="RCS block to append to system prompt (empty = use default)",
    )

    # Fallback
    fallback_compactor: ServerCompactorConfig = Field(
        default_factory=ServerCompactorConfig,
        description="Fallback compactor settings",
    )

    def get_rcs_system_block(self) -> str:
        """Return the RCS system block, using default if not overridden."""
        from nexus.config.defaults import DEFAULT_RCS_SYSTEM_BLOCK

        return self.rcs_system_block or DEFAULT_RCS_SYSTEM_BLOCK

    def get_context_updates_description(self) -> str:
        """Return the context updates param description."""
        from nexus.config.defaults import DEFAULT_CONTEXT_UPDATES_PARAM_DESC

        return self.context_updates_param_description or DEFAULT_CONTEXT_UPDATES_PARAM_DESC
