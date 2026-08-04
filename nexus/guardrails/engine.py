"""Guard engine running registered guards on hooks."""

from __future__ import annotations

import logging
from typing import Optional

from nexus.guardrails.protocol import GuardDecision, GuardProtocol, GuardResult
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)


class GuardEngine:
    """Runs guards in order; first block wins."""

    def __init__(self, guards: Optional[list[GuardProtocol]] = None):
        self.guards = list(guards or [])

    def add(self, guard: GuardProtocol) -> None:
        self.guards.append(guard)

    async def check_input(self, content: str, ctx: RunContext) -> GuardResult:
        return await self._run(content, ctx=ctx, phase="input")

    async def check_output(self, content: str, ctx: RunContext) -> GuardResult:
        return await self._run(content, ctx=ctx, phase="output")

    async def _run(self, content: str, *, ctx: RunContext, phase: str) -> GuardResult:
        current = content
        for guard in self.guards:
            try:
                result = await guard.check(current, ctx=ctx, phase=phase)
            except Exception as exc:
                logger.warning("Guard failed: %s", exc)
                continue
            if result.decision == GuardDecision.BLOCK:
                return result
            if result.decision == GuardDecision.REDACT and result.content is not None:
                current = result.content
        return GuardResult(decision=GuardDecision.ALLOW, content=current)
