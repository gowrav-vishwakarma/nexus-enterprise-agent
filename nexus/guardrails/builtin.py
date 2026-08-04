"""Built-in guard implementations."""

from __future__ import annotations

from nexus.guardrails.protocol import GuardDecision, GuardResult
from nexus.guardrails.redaction import redact_text
from nexus.tools.context import RunContext

_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "disregard your instructions",
    "system prompt",
    "you are now",
)


class PIIRedactionGuard:
    """Redact common PII patterns from text."""

    async def check(
        self,
        content: str,
        *,
        ctx: RunContext,
        phase: str = "input",
    ) -> GuardResult:
        redacted = redact_text(content)
        if redacted != content:
            return GuardResult(
                decision=GuardDecision.REDACT,
                content=redacted,
                reason="PII redacted",
            )
        return GuardResult(decision=GuardDecision.ALLOW, content=content)


class PromptInjectionGuard:
    """Block obvious prompt-injection phrases on input."""

    async def check(
        self,
        content: str,
        *,
        ctx: RunContext,
        phase: str = "input",
    ) -> GuardResult:
        if phase != "input":
            return GuardResult(decision=GuardDecision.ALLOW, content=content)
        lower = content.lower()
        for pattern in _INJECTION_PATTERNS:
            if pattern in lower:
                return GuardResult(
                    decision=GuardDecision.BLOCK,
                    reason=f"Prompt injection pattern detected: {pattern}",
                )
        return GuardResult(decision=GuardDecision.ALLOW, content=content)
