"""gRPC VAD client adapter — wraps remote VAD as local VADAdapter."""

from __future__ import annotations

import asyncio
from typing import Optional

import grpc

from nexus.realtime.adapters.vad.base import VADAdapter, VADEvent
from nexus.realtime.config import VADConfig
from nexus.server.metadata import run_context_to_metadata
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.resolve import resolve_grpc_target
from nexus.tools.context import RunContext


class GrpcVAD(VADAdapter):
    """VAD via Nexus media gRPC server.

    For half-duplex / utterance mode the adapter buffers frames locally and
    uses unary-style batching. For streaming, use the server's StreamVad via
    ``feed_frame`` in a background task (full-duplex pipelines use local VAD
    or this adapter with frame batching).
    """

    def __init__(
        self,
        config: VADConfig,
        *,
        registry=None,
        run_context: Optional[RunContext] = None,
    ) -> None:
        super().__init__(config)
        self._registry = registry
        self._run_context = run_context
        self._target = resolve_grpc_target(
            base_url=config.base_url,
            server_ref=config.server_ref,
            registry=registry,
            tenant_id=run_context.tenant_id if run_context else None,
        )
        self._channel: Optional[grpc.aio.Channel] = None
        self._utterance = b""
        self._pending_frames: list[bytes] = []
        self._loop = asyncio.get_event_loop_policy().get_event_loop()

    async def _stub(self) -> media_pb2_grpc.VadServiceStub:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._target)
        return media_pb2_grpc.VadServiceStub(self._channel)

    def _metadata(self):
        return run_context_to_metadata(self._run_context)

    def process_frame(self, frame: bytes) -> Optional[VADEvent]:
        """Buffer frame; run sync stub call when enough frames accumulated.

        For tests and simple paths, uses energy-like threshold on frame count.
        Production full-duplex should prefer local Silero or async VAD wrapper.
        """
        self._pending_frames.append(frame)
        # Batch ~10 frames then query server (sync bridge for VADAdapter sync API).
        if len(self._pending_frames) < 10:
            return None
        return self._flush_pending()

    def _flush_pending(self) -> Optional[VADEvent]:
        frames = self._pending_frames
        self._pending_frames = []

        async def _call():
            stub = await self._stub()

            async def _iter():
                for f in frames:
                    yield media_pb2.AudioFrame(pcm=f, sample_rate=self.config.sample_rate)
                yield media_pb2.AudioFrame(is_final=True, sample_rate=self.config.sample_rate)

            event = None
            async for ev in stub.StreamVad(_iter(), metadata=self._metadata()):
                if ev.event_type == media_pb2.VadEvent.SPEECH_START:
                    event = VADEvent.SPEECH_START
                elif ev.event_type == media_pb2.VadEvent.SPEECH_END:
                    self._utterance = ev.utterance_pcm
                    event = VADEvent.SPEECH_END
            return event

        try:
            return self._loop.run_until_complete(_call())
        except RuntimeError:
            # Inside running loop — schedule and return None this frame.
            return None

    def take_utterance(self) -> bytes:
        data = self._utterance
        self._utterance = b""
        return data

    def reset(self) -> None:
        self._utterance = b""
        self._pending_frames.clear()
