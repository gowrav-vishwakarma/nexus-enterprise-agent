"""Anthropic Claude provider adapter."""

import logging
from typing import Any, Optional

from nexus.config.llm import LLMProviderConfig
from nexus.llm.adapters.base import LLMAdapter
from nexus.llm.response import LLMResponse, TokenUsage, ToolCallRequest, LLMStreamChunk

logger = logging.getLogger(__name__)


class AnthropicAdapter(LLMAdapter):
    """Adapter for Anthropic Claude API."""

    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None
        self._async_client = None

    def _get_client(self):
        """Lazy load and initialize the async Anthropic client."""
        if self._async_client is not None:
            return self._async_client

        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required to use the Anthropic adapter. "
                "Install it using `pip install nexus-enterprise-agent[anthropic]`"
            )

        api_key_str = self.config.api_key.get_secret_value() if hasattr(self.config.api_key, "get_secret_value") else str(self.config.api_key)

        client_kwargs = {
            "api_key": api_key_str,
            "timeout": self.config.timeout,
            "max_retries": self.config.max_retries,
        }
        if self.config.base_url:
            client_kwargs["base_url"] = self.config.base_url

        self._async_client = anthropic.AsyncAnthropic(**client_kwargs)
        return self._async_client

    def _prepare_messages_and_system(self, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Optional[str]]:
        """Separate the system message and format others for Anthropic."""
        system_content = None
        formatted_messages = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                # Combine system messages if there are multiple
                if system_content:
                    system_content += "\n\n" + content
                else:
                    system_content = content
            else:
                # Map role types: user, assistant, tool
                # Anthropic expects 'user' or 'assistant'
                mapped_role = role
                if role == "tool":
                    mapped_role = "user"
                    # For tool responses, Anthropic expects a tool_result content block structure
                    content_blocks = []
                    # Wait, if content is already structured as tool_result or text:
                    # If content is a string:
                    tool_call_id = msg.get("tool_call_id") or msg.get("tool_use_id") or "tc_unknown"
                    content_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call_id,
                        "content": content
                    })
                    formatted_messages.append({
                        "role": "user",
                        "content": content_blocks
                    })
                elif role == "assistant" and msg.get("tool_calls"):
                    # For assistant messages that call tools, Anthropic expects tool_use blocks
                    content_blocks = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                    for tc in msg["tool_calls"]:
                        # Convert tc to Anthropic style if needed
                        # tool_calls contains ToolCallRecord or dictionary
                        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                        tc_name = tc.get("tool_name") if isinstance(tc, dict) else getattr(tc, "tool_name", None)
                        tc_input = tc.get("tool_input") if isinstance(tc, dict) else getattr(tc, "tool_input", None)
                        
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc_id,
                            "name": tc_name,
                            "input": tc_input
                        })
                    formatted_messages.append({
                        "role": "assistant",
                        "content": content_blocks
                    })
                else:
                    # String or list content
                    formatted_messages.append({
                        "role": mapped_role,
                        "content": content
                    })

        # Anthropic requires messages to start with user/assistant.
        # It also doesn't allow empty messages.
        return formatted_messages, system_content

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

        formatted_messages, system_prompt = self._prepare_messages_and_system(messages)

        # Anthropic messages API parameters
        params = {
            "model": self.config.model,
            "messages": formatted_messages,
            "max_tokens": max_tokens or 4096,  # Anthropic requires max_tokens
            **self.config.default_params,
        }

        if system_prompt:
            params["system"] = system_prompt

        if temperature is not None:
            params["temperature"] = temperature

        if stop_sequences:
            params["stop_sequences"] = stop_sequences

        if tools:
            # Map tools schema: Anthropic expects input_schema instead of parameters
            anthropic_tools = []
            for t in tools:
                anthropic_tools.append({
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"] if "parameters" in t else t.get("parameters_schema", {})
                })
            params["tools"] = anthropic_tools

        params.update(kwargs)

        try:
            response = await client.messages.create(**params)
        except Exception as e:
            logger.error("Anthropic API call failed: %s", e)
            raise

        text_content = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                text_content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.id,
                        tool_name=block.name,
                        tool_input=block.input,
                    )
                )

        # Map token usage
        usage = TokenUsage()
        if response.usage:
            usage.prompt_tokens = response.usage.input_tokens
            usage.completion_tokens = response.usage.output_tokens
            usage.total_tokens = response.usage.input_tokens + response.usage.output_tokens

        return LLMResponse(
            content=text_content if text_content else None,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=response.stop_reason or "stop",
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

        formatted_messages, system_prompt = self._prepare_messages_and_system(messages)

        params = {
            "model": self.config.model,
            "messages": formatted_messages,
            "max_tokens": max_tokens or 4096,
            **self.config.default_params,
        }

        if system_prompt:
            params["system"] = system_prompt

        if temperature is not None:
            params["temperature"] = temperature

        if tools:
            anthropic_tools = []
            for t in tools:
                anthropic_tools.append({
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"] if "parameters" in t else t.get("parameters_schema", {})
                })
            params["tools"] = anthropic_tools

        params.update(kwargs)

        try:
            stream = await client.messages.create(**params, stream=True)
        except Exception as e:
            logger.error("Anthropic Streaming API call failed: %s", e)
            raise

        current_tool_index = 0
        async for event in stream:
            if event.type == "content_block_start":
                block = event.content_block
                if block.type == "tool_use":
                    yield LLMStreamChunk(
                        tool_calls=[{
                            "index": current_tool_index,
                            "id": block.id,
                            "name": block.name,
                            "arguments": "",
                        }]
                    )
            elif event.type == "content_block_delta":
                delta = event.delta
                if delta.type == "text_delta":
                    yield LLMStreamChunk(content=delta.text)
                elif delta.type == "input_json_delta":
                    yield LLMStreamChunk(
                        tool_calls=[{
                            "index": current_tool_index,
                            "arguments": delta.partial_json,
                        }]
                    )
            elif event.type == "content_block_stop":
                current_tool_index += 1
            elif event.type == "message_delta":
                usage = None
                if hasattr(event, "usage") and event.usage:
                    usage = TokenUsage(
                        prompt_tokens=event.usage.input_tokens,
                        completion_tokens=event.usage.output_tokens,
                        total_tokens=event.usage.input_tokens + event.usage.output_tokens
                    )
                yield LLMStreamChunk(
                    finish_reason=event.delta.stop_reason,
                    usage=usage
                )
