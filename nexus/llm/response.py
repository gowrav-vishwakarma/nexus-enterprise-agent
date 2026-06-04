"""LLM response data models."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage statistics for an LLM call."""

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt")
    completion_tokens: int = Field(default=0, description="Tokens in the completion")
    total_tokens: int = Field(default=0, description="Total tokens used")
    cached_tokens: int = Field(default=0, description="Cached tokens in the prompt")


class ToolCallRequest(BaseModel):
    """A request from the LLM to call a tool."""

    id: str = Field(..., description="Unique ID of the tool call")
    tool_name: str = Field(..., description="Name of the tool to execute")
    tool_input: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class LLMResponse(BaseModel):
    """Complete response from an LLM call."""

    content: Optional[str] = Field(None, description="Text content of the response")
    tool_calls: list[ToolCallRequest] = Field(default_factory=list, description="Tool calls requested")
    usage: TokenUsage = Field(default_factory=TokenUsage, description="Token usage statistics")
    finish_reason: str = Field(default="stop", description="LLM finish reason")
    raw_response: dict[str, Any] = Field(default_factory=dict, description="Raw provider response")


class LLMStreamChunk(BaseModel):
    """A streaming chunk from an LLM response."""

    content: Optional[str] = Field(None, description="Incremental text content chunk")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, description="Incremental tool call chunks")
    usage: Optional[TokenUsage] = Field(None, description="Usage statistics (typically returned in the final chunk)")
    finish_reason: Optional[str] = Field(None, description="LLM finish reason if complete")
