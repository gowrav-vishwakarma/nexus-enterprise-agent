"""gRPC service base helpers."""

from __future__ import annotations

import asyncio
import logging
from concurrent import futures
from typing import Any

import grpc

from nexus.server.pool import EnginePool, TTSReplicaPool
from nexus.server.proto import media_pb2, media_pb2_grpc

logger = logging.getLogger(__name__)


class HealthServicer(media_pb2_grpc.HealthServiceServicer):
    def __init__(self, kind: str, engine: str, *, ready: bool = True, message: str = "") -> None:
        self.kind = kind
        self.engine = engine
        self.ready = ready
        self.message = message
        self.sample_rate = 16000
        self.languages: list[str] = []

    async def Check(self, request, context):  # noqa: N802
        status = "ok" if self.ready else "loading"
        return media_pb2.HealthResponse(status=status, engine=self.engine, message=self.message)

    async def Meta(self, request, context):  # noqa: N802
        return media_pb2.MetaResponse(
            kind=self.kind,
            engine=self.engine,
            sample_rate=self.sample_rate,
            languages=self.languages,
        )


def pcm16_to_float32(pcm: bytes):
    import numpy as np

    if not pcm:
        return np.array([], dtype=np.float32)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def float32_to_pcm16(audio) -> bytes:
    import numpy as np

    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


async def serve_grpc(
    servicers: list[tuple[Any, str]],
    *,
    host: str = "127.0.0.1",
    port: int = 50051,
) -> grpc.aio.Server:
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    for add_fn, servicer in servicers:
        add_fn(servicer, server)
    listen = f"{host}:{port}"
    server.add_insecure_port(listen)
    await server.start()
    logger.info("gRPC server listening on %s", listen)
    return server


_shared_pool = EnginePool()


def get_pool() -> EnginePool:
    return _shared_pool
