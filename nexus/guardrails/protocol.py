"""Guard protocol for input/output filtering."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from nexus.tools.context import RunContext


class GuardDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REDACT = "redact"


class GuardResult(BaseModel):
    decision: GuardDecision = GuardDecision.ALLOW
    content: Optional[str] = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class GuardProtocol(Protocol):
    """Input or output guard callable."""

    async def check(
        self,
        content: str,
        *,
        ctx: RunContext,
        phase: str = "input",
    ) -> GuardResult: ...
