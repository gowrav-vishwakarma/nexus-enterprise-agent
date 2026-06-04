"""OpenAI and Azure OpenAI provider adapter."""

import logging
from typing import Any, Optional

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest, LLMStreamChunk
from nexus.llm.tool_format import format_openai_tools

logger = logging.getLogger(__name__)


class OpenAIAdapter(LLMAdapter):
    """Adapter for OpenAI and Azure OpenAI APIs."""

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None
        self._async_client = None

    def _get_client(self):
        """Lazy load and initialize the async OpenAI client."""
        if self._async_client is not None:
            return self._async_client

        try:
            import openai
        except ImportError:
            raise ImportError(
                "The 'openai' package is required to use the OpenAI adapter. "
                "Install it using `pip install nexus-agent[openai]`"
            )

        api_key_str = self.config.api_key.get_secret_value() if hasattr(self.config.api_key, "get_secret_value") else str(self.config.api_key)

        client_kwargs = {
            "api_key": api_key_str,
            "timeout": self.config.timeout,
            "max_retries": self.config.max_retries,
        }
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url

        if self.config.provider == "azure_openai":
            if not self.config.api_version:
                raise ValueError("api_version is required for azure_openai provider")
            self._async_client = openai.AsyncAzureOpenAI(
                api_version=self.config.api_version,
                **client_kwargs
            )
        else:
            self._async_client = openai.AsyncOpenAI(**client_kwargs)

        return self._async_client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stop_sequences: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()

        # Prepare parameters
        params = {
            "model": self.config.model,
            "messages": messages,
            **self.config.default_params,
        }
        
        # Override with per-call parameters
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if stop_sequences:
            params["stop"] = stop_sequences
        
        if tools:
            params["tools"] = format_openai_tools(tools)

        # Merge extra params from config and kwargs
        params.update(self.config.extra_headers)
        params.update(kwargs)

        try:
            response = await client.chat.completions.create(**params)
        except Exception as e:
            logger.error("OpenAI API call failed: %s", e)
            raise

        choice = response.choices[0]
        message = choice.message

        # Map tool calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                import json
                try:
                    tool_input = json.loads(tc.function.arguments)
                except Exception:
                    tool_input = {}
                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        tool_name=tc.function.name,
                        tool_input=tool_input,
                    )
                )

        # Map token usage
        usage = TokenUsage()
        if response.usage:
            usage.prompt_tokens = response.usage.prompt_tokens
            usage.completion_tokens = response.usage.completion_tokens
            usage.total_tokens = response.usage.total_tokens
            if hasattr(response.usage, "prompt_tokens_details") and response.usage.prompt_tokens_details:
                usage.cached_tokens = getattr(response.usage.prompt_tokens_details, "cached_tokens", 0)

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
            raw_response=response.model_dump() if hasattr(response, "model_dump") else dict(response),
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Any:
        client = self._get_client()

        # Prepare parameters
        params = {
            "model": self.config.model,
            "messages": messages,
            "stream": True,
            **self.config.default_params,
        }
        
        # Override with per-call parameters
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        
        if tools:
            params["tools"] = format_openai_tools(tools)

        # Merge extra params from config and kwargs
        params.update(kwargs)

        try:
            stream = await client.chat.completions.create(**params)
            
            async def generator():
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    
                    choice = chunk.choices[0]
                    delta = choice.delta
                    
                    tool_calls = []
                    if delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            # We yield delta tool call info
                            tool_calls.append({
                                "index": tc_chunk.index,
                                "id": tc_chunk.id,
                                "name": tc_chunk.function.name if tc_chunk.function else None,
                                "arguments": tc_chunk.function.arguments if tc_chunk.function else None,
                            })

                    usage = None
                    if hasattr(chunk, "usage") and chunk.usage:
                        usage = TokenUsage(
                            prompt_tokens=chunk.usage.prompt_tokens,
                            completion_tokens=chunk.usage.completion_tokens,
                            total_tokens=chunk.usage.total_tokens,
                        )

                    yield LLMStreamChunk(
                        content=delta.content,
                        tool_calls=tool_calls,
                        usage=usage,
                        finish_reason=choice.finish_reason,
                    )
            return generator()
        except Exception as e:
            logger.error("OpenAI Streaming API call failed: %s", e)
            raise
