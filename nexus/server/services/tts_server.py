"""TTS gRPC service."""

from __future__ import annotations

import logging

from nexus.server.pool import TTSReplicaPool
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.services.base import HealthServicer, float32_to_pcm16

logger = logging.getLogger(__name__)


class TtsServicer(media_pb2_grpc.TtsServiceServicer):
    def __init__(self, pool: TTSReplicaPool, health: HealthServicer) -> None:
        self.pool = pool
        self.health = health

    async def Synthesize(self, request, context):  # noqa: N802
        eng = self.pool.acquire()
        audio = eng.synthesize(request.text, request.language or "hi", request.voice or None)
        return media_pb2.AudioChunk(
            pcm=float32_to_pcm16(audio),
            sample_rate=eng.sample_rate,
            text=request.text,
        )

    async def StreamSynthesize(self, request_iterator, context):  # noqa: N802
        text_parts: list[str] = []
        language = "hi"
        voice = None
        async for req in request_iterator:
            if req.text:
                text_parts.append(req.text)
            if req.language:
                language = req.language
            if req.voice:
                voice = req.voice
            if req.is_final:
                break
        text = "".join(text_parts).strip()
        if not text:
            return
        eng = self.pool.acquire()
        for chunk in eng.synthesize_stream(text, language, voice):
            yield media_pb2.AudioChunk(
                pcm=float32_to_pcm16(chunk),
                sample_rate=eng.sample_rate,
                text=text,
            )


def build_tts_server(
    engine_id: str,
    *,
    host: str,
    port: int,
    replicas: int = 1,
    extra: dict | None = None,
) -> tuple:
    extra = extra or {}
    pool = TTSReplicaPool(engine_id, replicas=replicas, **extra)
    health = HealthServicer("tts", engine_id, ready=True)
    health.sample_rate = pool.sample_rate
    servicer = TtsServicer(pool, health)
    return (
        media_pb2_grpc.add_TtsServiceServicer_to_server,
        servicer,
        media_pb2_grpc.add_HealthServiceServicer_to_server,
        health,
        host,
        port,
    )
