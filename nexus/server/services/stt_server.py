"""STT gRPC service."""

from __future__ import annotations

import logging

from nexus.server.engines.base import STTEngine
from nexus.server.pool import EnginePool
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.services.base import HealthServicer, pcm16_to_float32

logger = logging.getLogger(__name__)


class SttServicer(media_pb2_grpc.SttServiceServicer):
    def __init__(self, engine: STTEngine, health: HealthServicer) -> None:
        self.engine = engine
        self.health = health

    async def Transcribe(self, request, context):  # noqa: N802
        audio = pcm16_to_float32(request.pcm)
        text = self.engine.transcribe(audio, request.sample_rate or 16000, "hi")
        return media_pb2.TranscriptEvent(text=text, is_final=True, confidence=1.0)

    async def StreamTranscribe(self, request_iterator, context):  # noqa: N802
        chunks: list[bytes] = []
        sample_rate = 16000
        async for frame in request_iterator:
            if frame.pcm:
                chunks.append(frame.pcm)
            if frame.sample_rate:
                sample_rate = frame.sample_rate
            if frame.is_final:
                break
        audio = pcm16_to_float32(b"".join(chunks))
        if len(audio):
            text = self.engine.transcribe(audio, sample_rate, "hi")
            if text:
                yield media_pb2.TranscriptEvent(text=text, is_final=True, confidence=1.0)


def build_stt_server(
    engine_id: str,
    pool: EnginePool,
    *,
    host: str,
    port: int,
    extra: dict | None = None,
) -> tuple:
    extra = extra or {}
    engine = pool.get("stt", engine_id, **extra)  # type: ignore[assignment]
    health = HealthServicer("stt", engine_id, ready=engine.loaded)
    health.sample_rate = 16000
    health.languages = list(getattr(engine.meta, "languages", ()))
    servicer = SttServicer(engine, health)
    return (
        media_pb2_grpc.add_SttServiceServicer_to_server,
        servicer,
        media_pb2_grpc.add_HealthServiceServicer_to_server,
        health,
        host,
        port,
    )
