"""Tests for cascaded voice pipeline, VAD, IVR tools, and session transport."""

from unittest.mock import patch

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.realtime.adapters.stt.mock import MockSTT
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.adapters.vad.energy import EnergyVAD, _frame_rms
from nexus.realtime.config import RealtimeAgentConfig, STTConfig, VADConfig
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.realtime.session import RealtimeSession
from nexus.realtime.transport.memory import InMemoryTransport
from nexus.session.manager import SessionManager


def _rt_config(stt=None, duplex="full", tool_plugins=None) -> RealtimeAgentConfig:
    agent = AgentConfig(
        name="voice_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
        tool_plugins=tool_plugins or [],
    )
    return RealtimeAgentConfig(
        name="voice_agent",
        modality="voice_cascaded",
        duplex=duplex,
        agent=agent,
        stt=stt or STTConfig(provider="mock"),
    )


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
async def test_cascaded_process_text_emits_audio_per_sentence():
    pipeline = CascadedVoicePipeline(
        _rt_config(),
        storage_config=SessionManager(),
        stt=MockSTT(),
        tts=MockTTS(),
        vad=EnergyVAD(),
    )

    with patch.object(
        pipeline.runner.llm_proxy,
        "chat_stream",
        _mock_chat_stream(["Hello", ". ", "World", "."]),
    ):
        events = [
            ev async for ev in pipeline.process_text("hi there", session_id="voice-1")
        ]

    types = [e.event_type for e in events]
    assert types[0] == "transcript_final"
    assert events[0].content == "hi there"

    audio_events = [e for e in events if e.event_type == "audio_out"]
    assert [e.audio for e in audio_events] == [b"AUDIO:default:Hello.", b"AUDIO:default:World."]

    final = [e for e in events if e.event_type == "final_response"][0]
    assert final.content == "Hello. World."


@pytest.mark.asyncio
async def test_cascaded_process_utterance_uses_stt():
    pipeline = CascadedVoicePipeline(
        _rt_config(stt=STTConfig(provider="mock", extra={"transcript": "book a flight"})),
        storage_config=SessionManager(),
        stt=MockSTT(fixed_transcript="book a flight"),
        tts=MockTTS(),
    )
    with patch.object(
        pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Sure."])
    ):
        events = [
            ev async for ev in pipeline.process_utterance(b"\x00\x01", session_id="voice-2")
        ]
    transcript = [e for e in events if e.event_type == "transcript_final"][0]
    assert transcript.content == "book a flight"


def test_energy_vad_segments_speech():
    vad = EnergyVAD(VADConfig(silence_ms=100, min_speech_ms=40, sample_rate=16000))
    frame_samples = 320  # 20ms at 16kHz
    loud = (10000).to_bytes(2, "little", signed=True) * frame_samples
    silence = (0).to_bytes(2, "little", signed=True) * frame_samples

    assert _frame_rms(loud) > 0.02
    assert _frame_rms(silence) == 0.0

    events = []
    # 4 loud frames (80ms speech) then 6 silent frames (120ms > 100ms silence).
    for _ in range(4):
        ev = vad.process_frame(loud)
        if ev:
            events.append(ev.value)
    for _ in range(6):
        ev = vad.process_frame(silence)
        if ev:
            events.append(ev.value)

    assert "speech_start" in events
    assert "speech_end" in events
    assert len(vad.take_utterance()) > 0


@pytest.mark.asyncio
async def test_realtime_session_pumps_audio():
    pipeline = CascadedVoicePipeline(
        _rt_config(duplex="half"),
        storage_config=SessionManager(),
        stt=MockSTT(fixed_transcript="hello"),
        tts=MockTTS(),
        vad=EnergyVAD(VADConfig(silence_ms=100, min_speech_ms=40, sample_rate=16000)),
    )
    transport = InMemoryTransport()
    session = RealtimeSession(pipeline, transport, session_id="voice-3")

    frame_samples = 320
    loud = (12000).to_bytes(2, "little", signed=True) * frame_samples
    silence = (0).to_bytes(2, "little", signed=True) * frame_samples

    for _ in range(4):
        await transport.push_audio(loud)
    for _ in range(8):
        await transport.push_audio(silence)
    await transport.end_input()

    with patch.object(
        pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Hi back."])
    ):
        await session.run_audio()

    assert transport.sent_audio == [b"AUDIO:default:Hi back."]
    event_types = {e.event_type for e in transport.sent_events}
    assert "transcript_final" in event_types
    assert "final_response" in event_types


@pytest.mark.asyncio
async def test_ivr_plugin_actions_recorded():
    from nexus.realtime.tools.ivr import IVRMenuPlugin
    from nexus.tools.context import RunContext
    from nexus.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register_plugin(IVRMenuPlugin())
    ctx = RunContext(metadata={"dtmf_buffer": "42"})

    result = await registry.execute("ivr_menu", "collect_dtmf", {"num_digits": 2}, ctx)
    assert "42" in result

    transfer = await registry.execute(
        "ivr_menu", "transfer_call", {"destination": "billing"}, ctx
    )
    assert "billing" in transfer
    assert ctx.metadata["ivr_terminal"] is True
    assert any(a["action"] == "transfer" for a in ctx.metadata["ivr_actions"])
