"""LID gRPC service (unary)."""

from __future__ import annotations

import logging

from nexus.server.engines.base import LIDEngine
from nexus.server.pool import EnginePool
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.services.base import HealthServicer, pcm16_to_float32

logger = logging.getLogger(__name__)


class LidServicer(media_pb2_grpc.LidServiceServicer):
    def __init__(self, engine: LIDEngine, health: HealthServicer) -> None:
        self.engine = engine
        self.health = health

    async def DetectLanguage(self, request, context):  # noqa: N802
        audio = pcm16_to_float32(request.pcm)
        lang, conf, en_text = self.engine.detect(
            audio, request.sample_rate or 16000, request.fallback_language or "hi"
        )
        return media_pb2.LidResponse(
            language=lang, confidence=conf, english_text=en_text or ""
        )


def build_lid_server(
    engine_id: str,
    pool: EnginePool,
    *,
    host: str,
    port: int,
    extra: dict | None = None,
) -> tuple:
    extra = extra or {}
    engine = pool.get("lid", engine_id, **extra)  # type: ignore[assignment]
    health = HealthServicer("lid", engine_id, ready=engine.loaded)
    health.languages = list(getattr(engine.meta, "languages", ()))
    servicer = LidServicer(engine, health)
    return (
        media_pb2_grpc.add_LidServiceServicer_to_server,
        servicer,
        media_pb2_grpc.add_HealthServiceServicer_to_server,
        health,
        host,
        port,
    )
