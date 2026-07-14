"""End-to-end cascaded pipeline with mock gRPC media + mocked LLM."""

from unittest.mock import patch

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.realtime.adapters.vad.energy import EnergyVAD
from nexus.realtime.config import RealtimeAgentConfig, STTConfig, TTSConfig
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.session.manager import SessionManager
from tests.server.fixtures.mock_grpc_servers import start_mock_server, stop_servers


def _mock_chat_stream(text_chunks):
    async def chat_stream(*args, **kwargs):
        async def gen():
            for c in text_chunks:
                yield LLMStreamChunk(content=c)
            yield LLMStreamChunk(
                content=None,
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            )
        return gen()
    return chat_stream


@pytest.mark.asyncio
async def test_cascaded_pipeline_with_grpc_media():
    stt_srv = await start_mock_server("stt", 50201)
    tts_srv = await start_mock_server("tts", 50202)
    try:
        agent = AgentConfig(
            name="voice",
            llm=LLMProviderConfig(provider="litellm", model="mock/model", api_key="k"),
        )
        rt = RealtimeAgentConfig(
            name="voice",
            modality="voice_cascaded",
            duplex="half",
            agent=agent,
            stt=STTConfig(provider="nexus_server", base_url="127.0.0.1:50201"),
            tts=TTSConfig(provider="nexus_server", base_url="127.0.0.1:50202"),
        )
        pipeline = CascadedVoicePipeline(
            rt,
            storage_config=SessionManager(),
            vad=EnergyVAD(),
        )
        with patch.object(
            pipeline.runner.llm_proxy._adapter,
            "chat_stream",
            side_effect=_mock_chat_stream(["Hello. ", "World."]),
        ):
            events = []
            async for ev in pipeline.process_text("test input", speak=True):
                events.append(ev.event_type)
        assert "transcript_final" in events
        assert "content" in events
        assert "audio_out" in events
        assert "final_response" in events
    finally:
        await stop_servers([stt_srv, tts_srv])
