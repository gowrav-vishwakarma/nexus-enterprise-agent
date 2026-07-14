"""RealtimeSession: bind a transport to a voice pipeline.

The session pumps inbound audio from the transport into the pipeline, and pushes
the pipeline's events (audio + structured) back to the transport. It is the
runtime object a server creates per connection/call.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Optional, Protocol

from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.transport.base import Transport

logger = logging.getLogger(__name__)


class _VoicePipeline(Protocol):
    run_context: Any

    def process_audio_stream(
        self, audio_in: AsyncIterator[bytes], session_id: Optional[str] = None
    ) -> AsyncIterator[RealtimeStreamEvent]:
        ...

    def process_text(
        self, text: str, session_id: Optional[str] = None
    ) -> AsyncIterator[RealtimeStreamEvent]:
        ...


class RealtimeSession:
    """Drive one realtime connection end-to-end."""

    def __init__(
        self,
        pipeline: _VoicePipeline,
        transport: Transport,
        session_id: Optional[str] = None,
        event_emitter: Optional[Any] = None,
    ) -> None:
        self.pipeline = pipeline
        self.transport = transport
        self.session_id = session_id or getattr(pipeline.run_context, "session_id", None)
        self.event_emitter = event_emitter
        self._agent_id = getattr(
            getattr(pipeline, "config", None), "name", None
        )

    async def _emit_telemetry(self, event: RealtimeStreamEvent) -> None:
        """Mirror key realtime events to the framework event emitter (OTel, etc.)."""
        if self.event_emitter is None:
            return
        from nexus.events.models import NexusEvent, NexusEventType

        mapping = {
            "session_started": NexusEventType.REALTIME_SESSION_STARTED,
            "transcript_final": NexusEventType.REALTIME_TRANSCRIBED,
            "barge_in": NexusEventType.REALTIME_BARGE_IN,
            "final_response": NexusEventType.REALTIME_RESPONSE_COMPLETED,
            "error": NexusEventType.REALTIME_ERROR,
        }
        etype = mapping.get(event.event_type)
        if etype is None:
            return
        data = dict(event.data or {})
        if event.content is not None:
            data.setdefault("content", event.content)
        try:
            await self.event_emitter.emit(
                NexusEvent(
                    event_type=etype,
                    session_id=self.session_id,
                    agent_id=self._agent_id,
                    data=data,
                )
            )
        except Exception:  # pragma: no cover - telemetry must never break a call
            logger.debug("realtime telemetry emit failed", exc_info=True)

    async def _dispatch(self, event: RealtimeStreamEvent) -> None:
        """Send a pipeline event to the transport (audio + structured)."""
        if event.event_type == "audio_out" and event.audio is not None:
            await self.transport.send_audio(event.audio)
        await self.transport.send_event(event)
        await self._emit_telemetry(event)

    async def run_audio(self) -> None:
        """Stream audio from the transport through the pipeline until it ends."""
        try:
            run_initial = getattr(self.pipeline, "run_initial_response", None)
            if run_initial is not None:
                async for event in run_initial(session_id=self.session_id):
                    await self._dispatch(event)
            async for event in self.pipeline.process_audio_stream(
                self.transport.receive_audio(), session_id=self.session_id
            ):
                await self._dispatch(event)
        finally:
            await self._emit_session_ended()

    async def run_text(self, text: str) -> None:
        """Process a single text turn and push events to the transport."""
        async for event in self.pipeline.process_text(text, session_id=self.session_id):
            await self._dispatch(event)

    async def _emit_session_ended(self) -> None:
        """Emit a session-ended telemetry event when the audio loop finishes."""
        if self.event_emitter is None:
            return
        from nexus.events.models import NexusEvent, NexusEventType

        try:
            await self.event_emitter.emit(
                NexusEvent(
                    event_type=NexusEventType.REALTIME_SESSION_ENDED,
                    session_id=self.session_id,
                    agent_id=self._agent_id,
                )
            )
        except Exception:  # pragma: no cover
            logger.debug("realtime session-ended emit failed", exc_info=True)
