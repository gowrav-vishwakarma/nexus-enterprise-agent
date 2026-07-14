"""gRPC TTS client adapter."""

from __future__ import annotations

from typing import AsyncIterator, Optional

import grpc

from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.config import TTSConfig
from nexus.server.metadata import run_context_to_metadata
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.resolve import resolve_grpc_target
from nexus.tools.context import RunContext


class GrpcTTS(TTSAdapter):
    """TTS via Nexus media gRPC server."""

    def __init__(
        self,
        config: TTSConfig,
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

    async def _stub(self) -> media_pb2_grpc.TtsServiceStub:
        if self._channel is None:
            self._channel = grpc.aio.insecure_channel(self._target)
        return media_pb2_grpc.TtsServiceStub(self._channel)

    def _metadata(self):
        return run_context_to_metadata(self._run_context)

    async def synthesize(self, text: str) -> bytes:
        stub = await self._stub()
        resp = await stub.Synthesize(
            media_pb2.TtsRequest(text=text, voice=self.config.voice or ""),
            metadata=self._metadata(),
        )
        return resp.pcm

    async def stream_synthesize(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        stub = await self._stub()
        buffer = ""

        async def _request_iter():
            nonlocal buffer
            async for delta in text_stream:
                if delta:
                    buffer += delta
                    yield media_pb2.TtsRequest(text=delta)
            yield media_pb2.TtsRequest(text=buffer, is_final=True)

        async for chunk in stub.StreamSynthesize(_request_iter(), metadata=self._metadata()):
            if chunk.pcm:
                yield chunk.pcm
