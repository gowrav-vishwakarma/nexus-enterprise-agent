"""LLM provider adapters base interface."""

from abc import ABC, abstractmethod
from typing import Any, Optional

from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMResponse, TokenUsage


class LLMAdapter(ABC):
    """Abstract base class for LLM provider adapters."""
    
    def __init__(self, config: LLMProviderConfig):
        self.config = config
    
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a chat completion request."""
        ...
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Any:
        """Send a streaming chat completion request. Returns an async iterator."""
        ...
    
    def count_tokens(self, messages: list[dict[str, Any]], tools: Optional[list[dict[str, Any]]] = None) -> int:
        """Estimate token count for messages (override in subclass if provider has native method)."""
        from nexus.llm.token_counter import TokenCounter
        return TokenCounter.count_messages(messages, self.config.model)
