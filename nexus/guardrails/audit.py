"""Audit logging sink for tool calls, approvals, and guard decisions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from nexus.events.emitter import EventSink
from nexus.events.models import NexusEvent
from nexus.guardrails.redaction import redact_payload
from nexus.scope import ScopeLevel, scope_key
from nexus.tools.context import RunContext

logger = logging.getLogger(__name__)

# Event families worth an audit record: what ran, and what was gated.
AUDITED_PREFIXES = ("tool_call.", "human_in_loop.")


class AuditSink(EventSink):
    """Append-only audit log keyed by scope.

    Register it on a runner's emitter with the same `RunContext` the run uses, so
    every line carries the tenant and user it belongs to:

        emitter.register_sink(AuditSink(ctx=run_context))

    Records are redacted before they are written; an audit trail should prove
    *that* a tool ran, not archive the customer data it carried.
    """

    def __init__(
        self,
        *,
        ctx: Optional[RunContext] = None,
        logger_name: str = "nexus.audit",
        redact: bool = True,
    ):
        self.ctx = ctx or RunContext()
        self.redact = redact
        self._log = logging.getLogger(logger_name)

    async def record(
        self,
        event_type: str,
        *,
        ctx: Optional[RunContext] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> None:
        context = ctx or self.ctx
        payload = data or {}
        if self.redact:
            payload = redact_payload(payload)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "scope": scope_key(context, ScopeLevel.USER),
            "tenant_id": context.tenant_id,
            "company_id": context.company_id,
            "user_id": context.user_id,
            "session_id": context.session_id,
            "data": payload,
        }
        self._log.info(json.dumps(entry, default=str))

    async def emit(self, event: NexusEvent) -> None:
        """EventSink entry point — audits tool calls and human-in-loop decisions."""
        name = event.event_type.value
        if not name.startswith(AUDITED_PREFIXES):
            return
        await self.record(name, data=event.model_dump(mode="json"))

    # Kept so existing callers that wired the sink by hand keep working.
    async def on_event(self, event: NexusEvent) -> None:
        await self.emit(event)
