"""gRPC adapter integration tests against mock servers."""

import pytest

from nexus.realtime.adapters.stt.grpc import GrpcSTT
from nexus.realtime.adapters.tts.grpc import GrpcTTS
from nexus.realtime.config import STTConfig, TTSConfig
from nexus.server.metadata import run_context_to_metadata
from nexus.tools.context import RunContext
from tests.server.fixtures.mock_grpc_servers import start_mock_server, stop_servers


@pytest.mark.asyncio
async def test_grpc_stt_transcribe():
    server = await start_mock_server("stt", 50101)
    try:
        ctx = RunContext(tenant_id="t1", user_id="u1", session_id="s1")
        adapter = GrpcSTT(
            STTConfig(provider="nexus_server", base_url="127.0.0.1:50101"),
            run_context=ctx,
        )
        # minimal PCM16 frame
        pcm = b"\x00\x01" * 1600
        text = await adapter.transcribe(pcm, language="gu")
        assert "mock transcript" in text
        assert run_context_to_metadata(ctx)
    finally:
        await stop_servers([server])


@pytest.mark.asyncio
async def test_grpc_tts_synthesize():
    server = await start_mock_server("tts", 50102)
    try:
        adapter = GrpcTTS(
            TTSConfig(provider="nexus_server", base_url="127.0.0.1:50102"),
        )
        audio = await adapter.synthesize("hello world", language="hi")
        assert isinstance(audio, bytes)
        assert len(audio) > 0
    finally:
        await stop_servers([server])
