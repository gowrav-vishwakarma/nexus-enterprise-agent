"""LLM provider configuration models."""

from typing import Literal, Optional

from pydantic import BaseModel, Field, SecretStr


ProviderType = Literal[
    "openai",
    "anthropic",
    "gemini",
    "ollama",
    "litellm",
    "groq",
    "openrouter",
    "bedrock",
    "azure_openai",
    "custom",
]


class LLMProviderConfig(BaseModel):
    """Configuration for an LLM provider.

    All secrets and settings are passed explicitly - nothing read from env vars.
    """

    provider: ProviderType = "openai"
    model: str = "gpt-4o"
    api_key: SecretStr = SecretStr("")
    base_url: Optional[str] = None
    api_version: Optional[str] = None
    context_window_tokens: int = Field(
        default=128000,
        ge=1,
        description="Max tokens for context window budgeting (history pruning)",
    )
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0
    extra_headers: dict[str, str] = {}
    default_params: dict[str, object] = {}

    def get_api_key(self) -> str:
        """Return the raw API key string."""
        return self.api_key.get_secret_value()

    def model_dump_safe(self) -> dict:
        """Dump config with API key masked for logging."""
        data = self.model_dump()
        data["api_key"] = "***" + data["api_key"][-4:] if data["api_key"] else ""
        return data
