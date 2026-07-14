"""Tests for telephony codec, SIP transport, reconnect, telemetry, plan gating."""

import base64
import json

import pytest

from nexus.realtime.audio.mulaw import (
    downsample_pcm16,
    pcm16_to_ulaw,
    ulaw_to_pcm16,
)
from nexus.realtime.reconnect import connect_with_retry
from nexus.realtime.transport.sip import TwilioMediaStreamTransport


def _pcm(samples):
    return b"".join(int(s).to_bytes(2, "little", signed=True) for s in samples)


def test_mulaw_roundtrip_is_close():
    pcm = _pcm([0, 1000, -1000, 8000, -8000, 32000, -32000])
    encoded = pcm16_to_ulaw(pcm)
    assert len(encoded) == len(pcm) // 2
    decoded = ulaw_to_pcm16(encoded)
    assert len(decoded) == len(pcm)
    # mu-law is lossy but should preserve sign and rough magnitude.
    orig = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    back = [int.from_bytes(decoded[i : i + 2], "little", signed=True) for i in range(0, len(decoded), 2)]
    for o, b in zip(orig, back):
        assert (o >= 0) == (b >= 0)
        if abs(o) > 2000:
            assert abs(abs(b) - abs(o)) < abs(o) * 0.2 + 200


def test_downsample_halves_sample_count():
    pcm = _pcm(list(range(16)))
    out = downsample_pcm16(pcm, 16000, 8000)
    assert len(out) == len(pcm) // 2


class _FakeTelWS:
    """websockets-style fake (recv/send), so no starlette import is needed."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.sent = []

    async def recv(self):
        if self._frames:
            return self._frames.pop(0)
        raise RuntimeError("closed")

    async def send(self, data):
        self.sent.append(data)


@pytest.mark.asyncio
async def test_sip_transport_decodes_media_and_dtmf():
    pcm_in = _pcm([1000, -1000, 2000, -2000])
    payload = base64.b64encode(pcm16_to_ulaw(pcm_in)).decode("ascii")
    frames = [
        json.dumps({"event": "start", "streamSid": "SID1", "start": {"callSid": "CA1"}}),
        json.dumps({"event": "media", "media": {"payload": payload}}),
        json.dumps({"event": "dtmf", "dtmf": {"digit": "7"}}),
        json.dumps({"event": "stop"}),
    ]
    ws = _FakeTelWS(frames)
    dtmf_seen = []
    transport = TwilioMediaStreamTransport(ws, on_dtmf=dtmf_seen.append)

    received = [chunk async for chunk in transport.receive_audio()]
    assert len(received) == 1
    assert len(received[0]) == len(pcm_in)
    assert dtmf_seen == ["7"]
    assert transport.stream_sid == "SID1"

    # Sending audio should produce a Twilio media frame with a base64 payload.
    await transport.send_audio(pcm_in)
    sent = json.loads(ws.sent[-1])
    assert sent["event"] == "media"
    assert sent["streamSid"] == "SID1"
    assert base64.b64decode(sent["media"]["payload"])


@pytest.mark.asyncio
async def test_connect_with_retry_succeeds_after_failures():
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("nope")
        return "connected"

    result = await connect_with_retry(flaky, max_retries=5, base_delay=0.0, jitter=0.0)
    assert result == "connected"
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_connect_with_retry_reraises_after_exhaustion():
    async def always_fail():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        await connect_with_retry(always_fail, max_retries=2, base_delay=0.0, jitter=0.0)


@pytest.mark.asyncio
async def test_realtime_session_emits_telemetry():
    from unittest.mock import patch

    from nexus.config.agent import AgentConfig
    from nexus.config.llm import LLMProviderConfig
    from nexus.events.emitter import CustomCallbackSink, NexusEventEmitter
    from nexus.events.models import NexusEventType
    from nexus.llm.response import LLMStreamChunk, TokenUsage
    from nexus.realtime.adapters.stt.mock import MockSTT
    from nexus.realtime.adapters.tts.mock import MockTTS
    from nexus.realtime.adapters.vad.energy import EnergyVAD
    from nexus.realtime.config import RealtimeAgentConfig, VADConfig
    from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
    from nexus.realtime.session import RealtimeSession
    from nexus.realtime.transport.memory import InMemoryTransport
    from nexus.session.manager import SessionManager

    captured = []
    emitter = NexusEventEmitter()
    emitter.register_sink(CustomCallbackSink(lambda e: captured.append(e) or _noop()))

    agent = AgentConfig(
        name="va", llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test")
    )
    cfg = RealtimeAgentConfig(name="va", duplex="half", agent=agent)
    pipeline = CascadedVoicePipeline(
        cfg,
        storage_config=SessionManager(),
        stt=MockSTT(fixed_transcript="hi"),
        tts=MockTTS(),
        vad=EnergyVAD(VADConfig(silence_ms=100, min_speech_ms=40, sample_rate=16000)),
    )
    transport = InMemoryTransport()
    session = RealtimeSession(pipeline, transport, session_id="tel-1", event_emitter=emitter)

    frame = 320
    loud = (12000).to_bytes(2, "little", signed=True) * frame
    silence = (0).to_bytes(2, "little", signed=True) * frame
    for _ in range(4):
        await transport.push_audio(loud)
    for _ in range(8):
        await transport.push_audio(silence)
    await transport.end_input()

    async def chat_stream(*a, **k):
        async def gen():
            yield LLMStreamChunk(content="hello back")
            yield LLMStreamChunk(content=None, finish_reason="stop", usage=TokenUsage())
        return gen()

    with patch.object(pipeline.runner.llm_proxy, "chat_stream", chat_stream):
        await session.run_audio()

    types = {e.event_type for e in captured}
    assert NexusEventType.REALTIME_SESSION_STARTED in types
    assert NexusEventType.REALTIME_TRANSCRIBED in types
    assert NexusEventType.REALTIME_RESPONSE_COMPLETED in types
    assert NexusEventType.REALTIME_SESSION_ENDED in types


async def _noop():
    return None


def test_plan_gating():
    from examples.realtime_saas_api import RealtimeAccessError, check_realtime_access

    feats = check_realtime_access("pro", "voice_grpc", "voice_cascaded")
    assert feats["max_concurrent"] == 10

    with pytest.raises(RealtimeAccessError):
        check_realtime_access("starter", "voice_grpc")  # not allowed on starter
    with pytest.raises(RealtimeAccessError):
        check_realtime_access("pro", "voice_grpc", "voice_s2s")  # s2s is enterprise
    with pytest.raises(RealtimeAccessError):
        check_realtime_access("nonexistent", "ivr_support")
