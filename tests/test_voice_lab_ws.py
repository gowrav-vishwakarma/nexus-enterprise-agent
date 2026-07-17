"""Voice Lab WebSocket + cascaded pipeline e2e (mocked media/LLM)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.realtime.adapters.stt.mock import MockSTT
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.adapters.vad.energy import EnergyVAD
from nexus.realtime.config import RealtimeAgentConfig, STTConfig, VADConfig
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.session.manager import SessionManager


def _true_async_chat_stream(text_chunks):
    """True async generator — matches fixed OpenAI/LiteLLM adapters."""

    async def chat_stream(*args, **kwargs):
        for c in text_chunks:
            yield LLMStreamChunk(content=c)
        yield LLMStreamChunk(
            content=None,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
        )

    return chat_stream


def _pipeline() -> CascadedVoicePipeline:
    agent = AgentConfig(
        name="voice_grpc",
        llm=LLMProviderConfig(
            provider="litellm",
            model="openai/qwen",
            api_key="sk-test",
            base_url="http://localhost:4000",
        ),
    )
    return CascadedVoicePipeline(
        RealtimeAgentConfig(
            name="voice_grpc",
            modality="voice_cascaded",
            duplex="half",
            agent=agent,
            stt=STTConfig(provider="mock"),
        ),
        storage_config=SessionManager(),
        stt=MockSTT(fixed_transcript="नमस्ते"),
        tts=MockTTS(),
        vad=EnergyVAD(VADConfig(silence_ms=80, min_speech_ms=40, sample_rate=16000)),
    )


@pytest.mark.asyncio
async def test_cascaded_litellm_base_url_stream_no_error():
    """Regression for Voice Lab: litellm+base_url must not emit stream TypeErrors."""
    pipeline = _pipeline()
    adapter = pipeline.runner.llm_proxy._adapter

    adapter.chat_stream = _true_async_chat_stream(["Namaste", "."])

    events = [ev async for ev in pipeline.process_text("हलोद", session_id="e2e-1")]
    types = [e.event_type for e in events]
    assert "error" not in types
    assert "transcript_final" in types
    assert "audio_out" in types
    assert "final_response" in types
    final = next(e for e in events if e.event_type == "final_response")
    assert final.content == "Namaste."


def test_voice_lab_websocket_full_cycle():
    """HTTP session create + WebSocket audio → transcript + LLM reply + audio."""
    import examples.voice_lab as lab

    pipeline = _pipeline()
    adapter = pipeline.runner.llm_proxy._adapter
    adapter.chat_stream = _true_async_chat_stream(["Hi back", "."])

    class _FakeRuntime:
        @classmethod
        def from_manifest(cls, *_a, **_k):
            return cls()

        def build_pipeline(self, _name):
            return pipeline

    class _FakeSchema:
        servers: dict = {}

    class _FakeManifest:
        schema = _FakeSchema()

    lab._manifest = _FakeManifest()
    lab._registry = None
    lab._rt_config = pipeline.config

    frame = 320
    loud = (12000).to_bytes(2, "little", signed=True) * frame
    silence = (0).to_bytes(2, "little", signed=True) * frame

    with (
        patch.object(lab, "RealtimeRuntime", _FakeRuntime),
        patch.object(lab, "_load_manifest", return_value=lab._manifest),
        TestClient(lab.app) as client,
    ):
        created = client.post("/v1/realtime/sessions")
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        with client.websocket_connect(f"/v1/realtime/ws/{session_id}") as ws:
            for _ in range(5):
                ws.send_bytes(loud)
            for _ in range(10):
                ws.send_bytes(silence)

            texts: list[str] = []
            binary: list[bytes] = []
            for _ in range(40):
                msg = ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("text"):
                    texts.append(msg["text"])
                    if "final_response" in msg["text"]:
                        break
                if msg.get("bytes"):
                    binary.append(msg["bytes"])

    import json

    events = [json.loads(t) for t in texts]
    types = [e["event_type"] for e in events]
    assert "session_started" in types
    assert "transcript_final" in types
    assert "final_response" in types
    assert "error" not in types
    transcript = next(e for e in events if e["event_type"] == "transcript_final")
    assert transcript["content"] == "नमस्ते"
    final = next(e for e in events if e["event_type"] == "final_response")
    assert (final.get("content") or final.get("data", {}).get("final_response")) == "Hi back."
    assert binary  # TTS audio frames
