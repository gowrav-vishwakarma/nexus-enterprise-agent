"""LLM proxy to orchestrate multiple providers."""

import logging
from typing import Any, AsyncIterator, Optional

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, LLMStreamChunk

logger = logging.getLogger(__name__)


class LLMProxy:
    """Proxy class to interface with selected LLM providers transparently."""

    def __init__(self, config: LLMProviderConfig):
        self.config = config
        self._adapter = self._init_adapter()

    def _init_adapter(self) -> LLMAdapter:
        """Initialize the specific provider adapter.

        Routing is driven only by ``provider``. ``base_url`` is optional endpoint
        configuration passed through to whichever adapter is selected.

          - ``openai`` / ``azure_openai`` → native OpenAI adapter
          - ``anthropic``                 → native Anthropic adapter
          - everything else               → LiteLLMAdapter (litellm, gemini, groq,
                                            ollama, bedrock, openrouter, custom, …)

        Examples:
          - Direct OpenAI: ``provider="openai"``, no base_url
          - LiteLLM proxy via OpenAI SDK: ``provider="openai"``, ``base_url="http://…"``
          - LiteLLM proxy via litellm lib: ``provider="litellm"``, ``base_url="http://…"``
        """
        provider = self.config.provider

        if provider in ("openai", "azure_openai"):
            from nexus.llm.adapters.openai import OpenAIAdapter
            return OpenAIAdapter(self.config)

        if provider == "anthropic":
            from nexus.llm.adapters.anthropic import AnthropicAdapter
            return AnthropicAdapter(self.config)

        try:
            from nexus.llm.adapters.litellm import LiteLLMAdapter
            return LiteLLMAdapter(self.config)
        except ImportError:
            raise ValueError(
                f"Provider '{provider}' requires the LiteLLM adapter. "
                "Install it with: uv pip install litellm"
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Execute a chat completion call with the configured adapter."""
        return await self._adapter.chat(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stop_sequences=stop_sequences,
            **kwargs
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Execute a streaming chat completion call with the configured adapter."""
        return await self._adapter.chat_stream(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

    def count_tokens(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None) -> int:
        """Count tokens in messages and tools using the adapter's implementation."""
        return self._adapter.count_tokens(messages, tools)
