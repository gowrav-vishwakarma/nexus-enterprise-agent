"""gRPC TTS client adapter."""

from __future__ import annotations

from typing import Any, AsyncIterator, Optional

import grpc

from nexus.realtime.adapters.tts.base import TTSAdapter
from nexus.realtime.config import TTSConfig
from nexus.server.engines.tts_params import stringify_params
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

    def _request(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        params: dict[str, Any] | None = None,
        is_final: bool = False,
    ) -> media_pb2.TtsRequest:
        lang = language or self.config.effective_params().get("language") or ""
        voice_desc = voice or self.config.voice or ""
        merged = {**self.config.effective_params(), **(params or {})}
        rate = self.config.speed if speed is None else speed
        return media_pb2.TtsRequest(
            text=text,
            voice=voice_desc,
            language=str(lang) if lang else "",
            speed=float(rate),
            params=stringify_params(merged),
            is_final=is_final,
        )

    async def synthesize(
        self,
        text: str,
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        **kwargs: Any,
    ) -> bytes:
        stub = await self._stub()
        resp = await stub.Synthesize(
            self._request(text, language=language, voice=voice, speed=speed, params=kwargs),
            metadata=self._metadata(),
        )
        return resp.pcm

    async def stream_synthesize(
        self,
        text_stream: AsyncIterator[str],
        *,
        language: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        stub = await self._stub()
        buffer = ""

        async def _request_iter():
            nonlocal buffer
            async for delta in text_stream:
                if delta:
                    buffer += delta
                    yield self._request(
                        delta, language=language, voice=voice, speed=speed, params=kwargs
                    )
            yield self._request(
                buffer,
                language=language,
                voice=voice,
                speed=speed,
                params=kwargs,
                is_final=True,
            )

        async for chunk in stub.StreamSynthesize(_request_iter(), metadata=self._metadata()):
            if chunk.pcm:
                yield chunk.pcm
