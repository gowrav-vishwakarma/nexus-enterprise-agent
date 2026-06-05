"""Context summary configuration (rolling conversation summary)."""

from typing import Optional

from pydantic import BaseModel, Field

from nexus.config.llm import LLMProviderConfig


class ContextSummaryConfig(BaseModel):
    """Fold oldest chat turns into rolling summary_text when context fill exceeds a ratio."""

    summarize_on: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Trigger when context_tokens / context_window >= this (e.g. 0.8). "
            "None = disabled"
        ),
    )
    summary_prompt: str = Field(
        default="",
        description="Custom summary prompt (empty = DEFAULT_CONTEXT_SUMMARY_PROMPT)",
    )
    summary_llm: Optional[LLMProviderConfig] = Field(
        default=None,
        description="Dedicated LLM for summarization (falls back to agent's main LLM)",
    )
    turns_to_fold: int = Field(
        default=2,
        ge=1,
        description="Number of oldest unfoldable turns to fold per trigger",
    )
    max_summary_chars: int = Field(
        default=4000,
        ge=200,
        description="Max characters for rolling summary_text",
    )
    inject_into_prompt: bool = Field(
        default=True,
        description="Inject summary_text into the system prompt",
    )

    def get_summary_prompt(self) -> str:
        """Return the summary prompt, using the default if not overridden."""
        from nexus.config.defaults import DEFAULT_CONTEXT_SUMMARY_PROMPT

        return self.summary_prompt or DEFAULT_CONTEXT_SUMMARY_PROMPT
