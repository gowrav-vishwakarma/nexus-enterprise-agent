"""Audit sink and trace redaction.

Traces, webhooks, and log pipelines usually leave the tenant boundary, and tool
arguments routinely carry customer data. These cover the wrapper that strips it.
"""

from __future__ import annotations

import json
import logging

import pytest

from nexus.events.emitter import EventSink, NexusEventEmitter, RedactingEventSink
from nexus.events.models import AgentStartedEvent, NexusEvent, ToolCallStartedEvent
from nexus.guardrails.audit import AuditSink
from nexus.guardrails.redaction import redact_payload, redact_text
from nexus.tools.context import RunContext


class CollectingSink(EventSink):
    def __init__(self) -> None:
        self.events: list[NexusEvent] = []

    async def emit(self, event: NexusEvent) -> None:
        self.events.append(event)


def test_redact_text_masks_email_and_phone():
    assert redact_text("write to a@b.com or call 555-123-4567") == (
        "write to [EMAIL] or call [PHONE]"
    )


def test_redact_payload_masks_secret_keys_at_any_depth():
    payload = {
        "Authorization": "Bearer abc",
        "nested": {"api_key": "sk-1", "contact": "a@b.com"},
        "items": [{"token": "t1"}, "plain a@b.com"],
    }

    out = redact_payload(payload)

    assert out["Authorization"] == "[REDACTED]"
    assert out["nested"]["api_key"] == "[REDACTED]"
    assert out["nested"]["contact"] == "[EMAIL]"
    assert out["items"][0]["token"] == "[REDACTED]"
    assert out["items"][1] == "plain [EMAIL]"


@pytest.mark.asyncio
async def test_redacting_sink_cleans_typed_fields_not_just_data():
    """Tool args live on a typed field, which is exactly where the PII is."""
    collector = CollectingSink()
    emitter = NexusEventEmitter()
    emitter.register_sink(RedactingEventSink(collector))

    await emitter.emit(
        ToolCallStartedEvent(
            session_id="s1",
            agent_id="a1",
            tool_name="send_mail",
            tool_args={"to": "bob@example.com", "api_key": "sk-live-123"},
        )
    )

    sent = collector.events[0]
    assert sent.tool_args == {"to": "[EMAIL]", "api_key": "[REDACTED]"}


@pytest.mark.asyncio
async def test_redacting_sink_keeps_routing_fields_searchable():
    collector = CollectingSink()
    emitter = NexusEventEmitter()
    emitter.register_sink(RedactingEventSink(collector))

    await emitter.emit(
        AgentStartedEvent(
            session_id="s1", agent_name="billing", user_message="mail me at x@y.com"
        )
    )

    sent = collector.events[0]
    assert sent.session_id == "s1"
    assert sent.agent_name == "billing"
    assert sent.user_message == "mail me at [EMAIL]"


@pytest.mark.asyncio
async def test_audit_sink_records_scope_and_hides_secrets(caplog):
    emitter = NexusEventEmitter()
    emitter.register_sink(
        AuditSink(ctx=RunContext(tenant_id="acme", company_id="c1", user_id="u1"))
    )

    with caplog.at_level(logging.INFO, logger="nexus.audit"):
        await emitter.emit(
            ToolCallStartedEvent(
                session_id="s1",
                agent_id="a1",
                tool_name="charge_card",
                tool_args={"token": "tok_live_1"},
            )
        )

    entry = json.loads(caplog.records[-1].getMessage())
    assert entry["event"] == "tool_call.started"
    assert entry["tenant_id"] == "acme"
    assert entry["scope"] == "tenant:acme:company:c1:user:u1"
    assert entry["data"]["tool_args"]["token"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_audit_sink_ignores_unrelated_events(caplog):
    emitter = NexusEventEmitter()
    emitter.register_sink(AuditSink(ctx=RunContext(tenant_id="acme")))

    with caplog.at_level(logging.INFO, logger="nexus.audit"):
        await emitter.emit(AgentStartedEvent(session_id="s1", agent_name="a"))

    assert [r for r in caplog.records if r.name == "nexus.audit"] == []
