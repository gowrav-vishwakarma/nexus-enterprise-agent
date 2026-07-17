"""LLM proxy to orchestrate multiple providers."""

import inspect
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
        """Initialize the LLM adapter.

        Every provider routes through the single :class:`LiteLLMAdapter`, which
        gives one consistent path for tool calls, streaming, reasoning controls,
        and usage across OpenAI, Anthropic, Gemini, Groq, Ollama, and any
        self-hosted OpenAI-compatible proxy (LiteLLM proxy, vLLM, SGLang, …).

        ``provider`` only influences model-string prefixing; ``base_url`` selects
        the self-hosted pass-through (model name sent verbatim). Examples:
          - Direct OpenAI:      ``provider="openai"`` (or ``litellm``), no base_url
          - Anthropic:          ``provider="anthropic"``, no base_url
          - Self-hosted proxy:  ``provider="litellm"``, ``base_url="http://…"``
        """
        try:
            from nexus.llm.adapters.litellm import LiteLLMAdapter
            return LiteLLMAdapter(self.config)
        except ImportError:
            raise ValueError(
                f"Provider '{self.config.provider}' requires the LiteLLM adapter. "
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
        """Yield stream chunks from the configured adapter."""
        stream = self._adapter.chat_stream(
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if inspect.iscoroutine(stream):
            stream = await stream
        async for chunk in stream:
            yield chunk

    def count_tokens(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None) -> int:
        """Count tokens in messages and tools using the adapter's implementation."""
        return self._adapter.count_tokens(messages, tools)
