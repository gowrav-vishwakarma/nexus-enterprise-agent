"""OpenAI-compatible tool schema and assistant message formatting."""

import json
from typing import Any, Optional

from nexus.llm.response import ToolCallRequest


def format_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wrap Nexus tool registry schemas for OpenAI / LiteLLM chat completions."""
    result: list[dict[str, Any]] = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            result.append(t)
        else:
            result.append({"type": "function", "function": t})
    return result


def tool_calls_to_openai_messages(tool_calls: list[ToolCallRequest]) -> list[dict[str, Any]]:
    """Serialize ToolCallRequest list for assistant message history replay."""
    messages: list[dict[str, Any]] = []
    for tc in tool_calls:
        messages.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": json.dumps(tc.tool_input),
                },
            }
        )
    return messages
