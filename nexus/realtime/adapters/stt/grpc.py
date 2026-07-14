"""gRPC STT client adapter."""

from __future__ import annotations

from typing import AsyncIterator, Optional

import grpc

from nexus.realtime.adapters.stt.base import STTAdapter, STTResult
from nexus.realtime.config import STTConfig
from nexus.server.metadata import run_context_to_metadata
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.resolve import resolve_grpc_target
from nexus.tools.context import RunContext


class GrpcSTT(STTAdapter):
    """STT via Nexus media gRPC server."""

    def __init__(
        self,
        config: STTConfig,
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

    async def _stub(self) -> media_pb2_grpc.SttServiceStub:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._target)
        return media_pb2_grpc.SttServiceStub(self._channel)

    def _metadata(self):
        return run_context_to_metadata(self._run_context)

    async def transcribe(self, audio: bytes, mime_type: str = "audio/wav") -> str:
        stub = await self._stub()
        resp = await stub.Transcribe(
            media_pb2.AudioFrame(
                pcm=audio,
                sample_rate=self.config.sample_rate,
                is_final=True,
            ),
            metadata=self._metadata(),
        )
        return resp.text

    async def stream_transcribe(
        self, audio_stream: AsyncIterator[bytes]
    ) -> AsyncIterator[STTResult]:
        stub = await self._stub()

        async def _request_iter():
            async for chunk in audio_stream:
                yield media_pb2.AudioFrame(
                    pcm=chunk,
                    sample_rate=self.config.sample_rate,
                )
            yield media_pb2.AudioFrame(is_final=True, sample_rate=self.config.sample_rate)

        async for event in stub.StreamTranscribe(_request_iter(), metadata=self._metadata()):
            if event.text:
                yield STTResult(
                    text=event.text,
                    is_final=event.is_final,
                    confidence=event.confidence or 1.0,
                )
