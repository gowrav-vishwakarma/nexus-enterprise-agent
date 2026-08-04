"""Mock LLM adapter for tests and eval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage


@dataclass
class MockLLMResponse:
    content: Optional[str] = "mock response"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class MockLLMAdapter(LLMAdapter):
    """Scripted LLM responses for deterministic tests."""

    def __init__(
        self,
        config: LLMProviderConfig,
        responses: Optional[list[MockLLMResponse]] = None,
    ):
        super().__init__(config)
        self.responses = list(responses or [MockLLMResponse()])
        self._index = 0
        self.calls: list[list[dict[str, Any]]] = []

    def _next(self) -> MockLLMResponse:
        if self._index >= len(self.responses):
            return self.responses[-1]
        resp = self.responses[self._index]
        self._index += 1
        return resp

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append(messages)
        scripted = self._next()
        from nexus.llm.response import ToolCallRequest

        tcs = [
            ToolCallRequest(
                id=tc.get("id", f"call_{i}"),
                tool_name=tc["name"],
                tool_input=tc.get("arguments", {}),
            )
            for i, tc in enumerate(scripted.tool_calls)
        ]
        return LLMResponse(content=scripted.content, tool_calls=tcs, usage=TokenUsage())

    async def chat_stream(self, messages: list[dict[str, Any]], **kwargs: Any) -> AsyncIterator[LLMStreamChunk]:
        resp = await self.chat(messages, **kwargs)
        if resp.content:
            yield LLMStreamChunk(content=resp.content, usage=resp.usage, finish_reason="stop")
