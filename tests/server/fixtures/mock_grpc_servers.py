"""In-process mock gRPC media servers for tests."""

from __future__ import annotations

import asyncio
from concurrent import futures

import grpc

from nexus.server.engines.mock import (
    MockLIDEngine,
    MockSTTEngine,
    MockTTSEngine,
    MockVADEngine,
    float32_to_pcm16,
)
from nexus.server.pool import EnginePool, TTSReplicaPool
from nexus.server.proto import media_pb2, media_pb2_grpc
from nexus.server.services.base import HealthServicer
from nexus.server.services.lid_server import LidServicer
from nexus.server.services.stt_server import SttServicer
from nexus.server.services.tts_server import TtsServicer
from nexus.server.services.vad_server import VadServicer


async def start_mock_server(kind: str, port: int, *, host: str = "127.0.0.1") -> grpc.aio.Server:
    pool = EnginePool()
    health = HealthServicer(kind, "mock", ready=True)
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=4))

    if kind == "stt":
        engine = MockSTTEngine()
        engine.load()
        health.languages = list(engine.meta.languages)
        media_pb2_grpc.add_SttServiceServicer_to_server(SttServicer(engine, health), server)
    elif kind == "tts":
        tts_pool = TTSReplicaPool("mock", replicas=1)
        health.sample_rate = tts_pool.sample_rate
        media_pb2_grpc.add_TtsServiceServicer_to_server(TtsServicer(tts_pool, health), server)
    elif kind == "vad":
        engine = MockVADEngine()
        engine.load()
        media_pb2_grpc.add_VadServiceServicer_to_server(VadServicer(engine, health), server)
    elif kind == "lid":
        engine = MockLIDEngine()
        engine.load()
        health.languages = list(engine.meta.languages)
        media_pb2_grpc.add_LidServiceServicer_to_server(LidServicer(engine, health), server)
    else:
        raise ValueError(kind)

    media_pb2_grpc.add_HealthServiceServicer_to_server(health, server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    return server


async def start_mock_stack(ports: dict[str, int]) -> list[grpc.aio.Server]:
    servers = []
    for kind, port in ports.items():
        servers.append(await start_mock_server(kind, port))
    return servers


async def stop_servers(servers: list[grpc.aio.Server]) -> None:
    for s in servers:
        await s.stop(grace=1)
