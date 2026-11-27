"""Tests for full-duplex turn handling (barge-in) in the cascaded pipeline."""

import asyncio

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.realtime.adapters.stt.mock import MockSTT
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.adapters.vad.energy import EnergyVAD
from nexus.realtime.config import RealtimeAgentConfig, VADConfig
from nexus.realtime.events import RealtimeStreamEvent
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.session.manager import SessionManager


def _pipeline(duplex="full"):
    agent = AgentConfig(
        name="va",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
    )
    vad_cfg = VADConfig(
        silence_ms=100,
        min_speech_ms=40,
        barge_in_min_speech_ms=0,  # interrupt on first speech frame
        sample_rate=16000,
    )
    cfg = RealtimeAgentConfig(name="va", duplex=duplex, agent=agent, vad=vad_cfg)
    return CascadedVoicePipeline(
        cfg,
        storage_config=SessionManager(),
        stt=MockSTT(fixed_transcript="hi"),
        tts=MockTTS(),
        vad=EnergyVAD(vad_cfg),
    )


async def _audio_with_barge_in():
    """Utterance, silence (end), then more speech mid-response (barge-in)."""
    frame = 320
    loud = (12000).to_bytes(2, "little", signed=True) * frame
    silence = (0).to_bytes(2, "little", signed=True) * frame
    # First utterance.
    for _ in range(4):
        yield loud
    for _ in range(8):
        yield silence
    # Give the response task a moment to start.
    await asyncio.sleep(0.01)
    # Second utterance (interrupts).
    for _ in range(4):
        yield loud
    for _ in range(8):
        yield silence


@pytest.mark.asyncio
async def test_full_duplex_emits_session_started_and_responses():
    pipeline = _pipeline("full")

    # Slow the response so barge-in can interrupt deterministically.
    async def slow_process(utterance, session_id=None, mime_type="audio/wav"):
        yield RealtimeStreamEvent.transcript("hi", final=True)
        await asyncio.sleep(0.05)
        yield RealtimeStreamEvent.text_delta("responding")
        await asyncio.sleep(0.05)
        yield RealtimeStreamEvent(event_type="final_response", content="responding")

    pipeline.process_utterance = slow_process  # type: ignore[assignment]

    events = [
        ev
        async for ev in pipeline.process_audio_stream(
            _audio_with_barge_in(), session_id="bd-1"
        )
    ]
    types = [e.event_type for e in events]
    assert types[0] == "session_started"
    # A barge-in should be emitted when the second utterance interrupts.
    assert "barge_in" in types


@pytest.mark.asyncio
async def test_half_duplex_no_barge_in():
    pipeline = _pipeline("half")
    frame = 320
    loud = (12000).to_bytes(2, "little", signed=True) * frame
    silence = (0).to_bytes(2, "little", signed=True) * frame

    async def audio():
        for _ in range(4):
            yield loud
        for _ in range(8):
            yield silence

    from unittest.mock import patch

    from nexus.llm.response import LLMStreamChunk, TokenUsage

    async def chat_stream(*a, **k):
        async def gen():
            yield LLMStreamChunk(content="ok")
            yield LLMStreamChunk(content=None, finish_reason="stop", usage=TokenUsage())
        return gen()

    with patch.object(pipeline.runner.llm_proxy, "chat_stream", chat_stream):
        events = [ev async for ev in pipeline.process_audio_stream(audio(), session_id="hd-1")]
    types = [e.event_type for e in events]
    assert "barge_in" not in types
    assert "final_response" in types


def _barge_pipeline():
    agent = AgentConfig(
        name="va",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
    )
    vad_cfg = VADConfig(
        silence_ms=500, min_speech_ms=40, barge_in_min_speech_ms=250, sample_rate=16000
    )
    cfg = RealtimeAgentConfig(name="va", duplex="full", agent=agent, vad=vad_cfg)
    pipeline = CascadedVoicePipeline(
        cfg, storage_config=SessionManager(), tts=MockTTS(), vad=EnergyVAD(vad_cfg)
    )

    async def long_reply(utterance, session_id=None, mime_type="audio/wav"):
        yield RealtimeStreamEvent.text_delta("talking")
        await asyncio.sleep(1.0)

    pipeline.process_utterance = long_reply  # type: ignore[assignment]
    return pipeline


async def _barged(interrupt_frames: int) -> bool:
    """Utterance, then `interrupt_frames` x 20 ms of loud audio + silence during the reply."""
    loud = (12000).to_bytes(2, "little", signed=True) * 320
    silence = (0).to_bytes(2, "little", signed=True) * 320

    async def mic():
        for frame in [loud] * 10 + [silence] * 30:
            yield frame
        await asyncio.sleep(0.05)  # the reply is now running
        for frame in [loud] * interrupt_frames + [silence] * 30:
            yield frame
            await asyncio.sleep(0)

    stream = _barge_pipeline().process_audio_stream(mic(), session_id="barge")
    try:
        async for ev in stream:
            if ev.event_type == "barge_in":
                return True
        return False
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_short_noise_does_not_barge_in():
    # 60 ms burst then silence: the silence must not count toward 250 ms of speech.
    assert not await _barged(3)


@pytest.mark.asyncio
async def test_real_speech_barges_in():
    assert await _barged(20)  # 400 ms of speech
