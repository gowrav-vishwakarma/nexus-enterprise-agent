"""Error taxonomy for Nexus agent framework.

Maps provider and runtime failures to typed exceptions so callers, retries,
guardrails, and product error pages can branch consistently.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """Stable error codes for programmatic handling."""

    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_AUTH = "llm_auth"
    LLM_CONTEXT_LENGTH = "llm_context_length"
    LLM_PROVIDER = "llm_provider"
    LLM_TIMEOUT = "llm_timeout"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_EXECUTION = "tool_execution"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_APPROVAL_REQUIRED = "tool_approval_required"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    TURN_TIMEOUT = "turn_timeout"
    VALIDATION = "validation"


class NexusError(Exception):
    """Base exception for Nexus framework errors."""

    code: ErrorCode = ErrorCode.LLM_PROVIDER

    def __init__(self, message: str, *, code: Optional[ErrorCode] = None, cause: Optional[BaseException] = None):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.cause = cause


class LLMError(NexusError):
    """LLM provider or proxy failure."""

    code: ErrorCode = ErrorCode.LLM_PROVIDER


class LLMRateLimitError(LLMError):
    code = ErrorCode.LLM_RATE_LIMIT


class LLMAuthError(LLMError):
    code = ErrorCode.LLM_AUTH


class LLMContextLengthError(LLMError):
    code = ErrorCode.LLM_CONTEXT_LENGTH


class LLMTimeoutError(LLMError):
    code = ErrorCode.LLM_TIMEOUT


class ToolError(NexusError):
    """Tool registry or execution failure."""

    code: ErrorCode = ErrorCode.TOOL_EXECUTION

    def __init__(
        self,
        message: str,
        *,
        tool_name: str = "",
        code: Optional[ErrorCode] = None,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message, code=code, cause=cause)
        self.tool_name = tool_name


class ToolTimeoutError(ToolError):
    code = ErrorCode.TOOL_TIMEOUT


class ToolApprovalRequiredError(ToolError):
    code = ErrorCode.TOOL_APPROVAL_REQUIRED


class GuardrailError(NexusError):
    """Input/output guard blocked the request."""

    code = ErrorCode.GUARDRAIL_BLOCKED


class BudgetExceededError(NexusError):
    """Run exceeded configured token or cost budget."""

    code = ErrorCode.BUDGET_EXCEEDED


class RateLimitExceededError(NexusError):
    """Tenant or scope rate limit exceeded."""

    code = ErrorCode.RATE_LIMIT_EXCEEDED


class TurnTimeoutError(NexusError):
    """Agent turn exceeded configured timeout."""

    code = ErrorCode.TURN_TIMEOUT


class ValidationError(NexusError):
    """Structured output or schema validation failed."""

    code = ErrorCode.VALIDATION


def classify_litellm_error(exc: BaseException) -> LLMError:
    """Map a LiteLLM (or OpenAI-compatible) exception to a typed LLMError."""
    msg = str(exc).lower()
    exc_type = type(exc).__name__.lower()

    if "rate" in msg or "429" in msg or "ratelimit" in exc_type:
        return LLMRateLimitError(str(exc), cause=exc)
    if "auth" in msg or "401" in msg or "403" in msg or "api key" in msg:
        return LLMAuthError(str(exc), cause=exc)
    if "context" in msg or "token" in msg and "limit" in msg or "too long" in msg:
        return LLMContextLengthError(str(exc), cause=exc)
    if "timeout" in msg or "timed out" in msg:
        return LLMTimeoutError(str(exc), cause=exc)
    return LLMError(str(exc), cause=exc)
