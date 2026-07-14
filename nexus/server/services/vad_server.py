"""VAD gRPC service — one session per RPC stream."""

from __future__ import annotations

import logging

from nexus.server.engines.base import VADEngine
from nexus.server.pool import EnginePool
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.services.base import HealthServicer

logger = logging.getLogger(__name__)


class VadServicer(media_pb2_grpc.VadServiceServicer):
    def __init__(self, engine: VADEngine, health: HealthServicer) -> None:
        self.engine = engine
        self.health = health

    async def StreamVad(self, request_iterator, context):  # noqa: N802
        session = self.engine.create_session()
        async for frame in request_iterator:
            if not frame.pcm:
                continue
            event = session.process_frame(frame.pcm)
            if event == "speech_start":
                yield media_pb2.VadEvent(
                    event_type=media_pb2.VadEvent.SPEECH_START,
                    sample_rate=frame.sample_rate or 16000,
                )
            elif event == "speech_end":
                utterance = session.take_utterance()
                yield media_pb2.VadEvent(
                    event_type=media_pb2.VadEvent.SPEECH_END,
                    utterance_pcm=utterance,
                    sample_rate=frame.sample_rate or 16000,
                )


def build_vad_server(
    engine_id: str,
    pool: EnginePool,
    *,
    host: str,
    port: int,
    extra: dict | None = None,
) -> tuple:
    extra = extra or {}
    engine = pool.get("vad", engine_id, **extra)  # type: ignore[assignment]
    health = HealthServicer("vad", engine_id, ready=engine.loaded)
    health.sample_rate = 16000
    servicer = VadServicer(engine, health)
    return (
        media_pb2_grpc.add_VadServiceServicer_to_server,
        servicer,
        media_pb2_grpc.add_HealthServiceServicer_to_server,
        health,
        host,
        port,
    )
