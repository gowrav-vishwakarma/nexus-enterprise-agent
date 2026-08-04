"""Event emitter and sinks for the Nexus Agent Framework."""

import abc
import logging
import sys
from typing import Awaitable, Callable, Optional

from nexus.events.models import NexusEvent

logger = logging.getLogger(__name__)


class EventSink(abc.ABC):
    """Abstract base class for event sinks."""

    @abc.abstractmethod
    async def emit(self, event: NexusEvent) -> None:
        """Emit the event to the sink."""
        ...


class StdoutEventSink(EventSink):
    """Event sink that prints events to standard output."""

    async def emit(self, event: NexusEvent) -> None:
        print(f"[{event.timestamp.isoformat()}] [{event.event_type.value}] {event.model_dump_json()}", file=sys.stdout)


class CustomCallbackSink(EventSink):
    """Event sink that forwards events to an async callback function."""

    def __init__(self, callback: Callable[[NexusEvent], Awaitable[None]]):
        self.callback = callback

    async def emit(self, event: NexusEvent) -> None:
        try:
            await self.callback(event)
        except Exception as e:
            logger.error("Error in custom callback event sink: %s", e)


class WebhookEventSink(EventSink):
    """Event sink that sends events to a webhook URL (SaaS-friendly)."""

    def __init__(self, url: str, headers: Optional[dict[str, str]] = None, timeout: int = 5):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client = None

    async def emit(self, event: NexusEvent) -> None:
        import httpx
        if not self._client:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        try:
            await self._client.post(self.url, json=event.to_dict(), headers=self.headers)
        except Exception as e:
            logger.error("Failed to send event %s to webhook %s: %s", event.event_id, self.url, e)


class OTelEventSink(EventSink):
    """Event sink that exports events to OpenTelemetry Tracer/Logger."""

    def __init__(self, tracer_name: str = "nexus"):
        self.tracer_name = tracer_name
        self._tracer = None
        try:
            from opentelemetry import trace
            self._tracer = trace.get_tracer(self.tracer_name)
        except ImportError:
            logger.warning("opentelemetry-api not installed. OTelEventSink will be no-op.")

    async def emit(self, event: NexusEvent) -> None:
        if not self._tracer:
            return
        
        # In OTel, we create an inline event/span representation
        with self._tracer.start_as_current_span(event.event_type.value) as span:
            span.set_attribute("event_id", event.event_id)
            if event.session_id:
                span.set_attribute("session_id", event.session_id)
            if event.agent_id:
                span.set_attribute("agent_id", event.agent_id)
            if event.turn_index is not None:
                span.set_attribute("turn_index", event.turn_index)
            for k, v in event.data.items():
                span.set_attribute(f"data.{k}", str(v))


class RedactingEventSink(EventSink):
    """Wrap any sink so PII and secrets never reach it.

    Traces, webhooks, and log aggregators are usually third-party systems, and
    tool arguments routinely carry customer data. Wrap the sink rather than
    trusting every backend:

        emitter.register_sink(RedactingEventSink(WebhookEventSink(url)))
    """

    #: Identity and routing fields, kept as-is so traces stay searchable.
    PRESERVED_FIELDS = frozenset(
        {"event_id", "event_type", "timestamp", "session_id", "agent_id", "turn_index"}
    )

    def __init__(self, inner: EventSink, *, sensitive_keys: Optional[set[str]] = None):
        from nexus.guardrails.redaction import SENSITIVE_KEYS

        self.inner = inner
        self.sensitive_keys = (
            frozenset(k.lower() for k in sensitive_keys)
            if sensitive_keys is not None
            else SENSITIVE_KEYS
        )

    async def emit(self, event: NexusEvent) -> None:
        from nexus.guardrails.redaction import redact_payload

        updates = {
            name: redact_payload(
                getattr(event, name), sensitive_keys=self.sensitive_keys
            )
            for name in type(event).model_fields
            if name not in self.PRESERVED_FIELDS
        }
        await self.inner.emit(event.model_copy(update=updates))


class NexusEventEmitter:
    """Central event emitter managing sinks and dispatching events."""

    def __init__(self):
        self._sinks: list[EventSink] = []

    def register_sink(self, sink: EventSink) -> None:
        """Register a new event sink."""
        if sink not in self._sinks:
            self._sinks.append(sink)

    def unregister_sink(self, sink: EventSink) -> None:
        """Unregister an event sink."""
        if sink in self._sinks:
            self._sinks.remove(sink)

    async def emit(self, event: NexusEvent) -> None:
        """Dispatch event to all registered sinks asynchronously."""
        for sink in self._sinks:
            try:
                await sink.emit(event)
            except Exception as e:
                logger.error("Error emitting event %s to sink %s: %s", event.event_id, sink.__class__.__name__, e)
