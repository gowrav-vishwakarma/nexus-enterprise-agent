"""Tests for per-turn language detection and spoken language switching."""

from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.realtime.adapters.lid.base import LIDResult
from nexus.realtime.adapters.lid.mock import MockLID
from nexus.realtime.adapters.stt.mock import MockSTT
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.config import LIDConfig, RealtimeAgentConfig, STTConfig
from nexus.realtime.languages import detect_language_request
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.session.manager import SessionManager


def _rt_config(*, lid: LIDConfig | None = None) -> RealtimeAgentConfig:
    agent = AgentConfig(
        name="voice_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
    )
    return RealtimeAgentConfig(
        name="voice_agent",
        modality="voice_cascaded",
        duplex="full",
        agent=agent,
        stt=STTConfig(provider="mock", language="hi"),
        lid=lid,
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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("please talk to me in Gujarati", "gu"),
        ("गुजराती में बात करो", "gu"),
        ("my Gujarati friend called", None),
        ("hello there", None),
    ],
)
def test_detect_language_request(text, expected):
    assert detect_language_request(text) == expected


@pytest.mark.asyncio
async def test_language_detected_fresh_every_turn():
    lid = MockLID(LIDConfig(provider="mock"))
    lid.detect = AsyncMock(
        side_effect=[
            LIDResult(language="hi", confidence=1.0),
            LIDResult(language="en", confidence=1.0, english_text="hello"),
            LIDResult(language="gu", confidence=1.0),
        ]
    )
    stt = MockSTT()
    stt.transcribe = AsyncMock(side_effect=["hindi text", "should not run", "gujarati text"])

    pipeline = CascadedVoicePipeline(
        _rt_config(lid=LIDConfig(provider="mock")),
        storage_config=SessionManager(),
        stt=stt,
        tts=MockTTS(),
        lid=lid,
    )

    with patch.object(pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Ok."])):
        for expected in ("hi", "en", "gu"):
            events = [ev async for ev in pipeline.process_utterance(b"audio", session_id="s1")]
            transcript = [e for e in events if e.event_type == "transcript_final"][0]
            assert transcript.data["language"] == expected

    assert lid.detect.await_count == 3
    assert stt.transcribe.await_count == 2


@pytest.mark.asyncio
async def test_english_detected_skips_conformer_when_no_whisper_text():
    lid = MockLID(LIDConfig(provider="mock"))
    lid.detect = AsyncMock(
        return_value=LIDResult(language="en", confidence=0.9, english_text=None),
    )
    stt = MockSTT()
    stt.transcribe = AsyncMock(return_value="should not run")

    pipeline = CascadedVoicePipeline(
        _rt_config(lid=LIDConfig(provider="mock")),
        storage_config=SessionManager(),
        stt=stt,
        tts=MockTTS(),
        lid=lid,
    )

    events = [ev async for ev in pipeline.process_utterance(b"audio", session_id="s-en")]
    assert stt.transcribe.await_count == 0
    assert any(e.event_type == "event" and e.data.get("info") == "empty_transcript" for e in events)


@pytest.mark.asyncio
async def test_spoken_language_switch_sticks_for_llm_tts():
    lid = MockLID(LIDConfig(provider="mock"), fixed_language="hi")
    lid.detect = AsyncMock(
        return_value=LIDResult(language="hi", confidence=1.0),
    )
    stt = MockSTT(fixed_transcript="please talk to me in Gujarati")

    pipeline = CascadedVoicePipeline(
        _rt_config(lid=LIDConfig(provider="mock")),
        storage_config=SessionManager(),
        stt=stt,
        tts=MockTTS(),
        lid=lid,
    )

    with patch.object(pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Ok."])):
        events = [ev async for ev in pipeline.process_utterance(b"audio", session_id="s2")]

    transcript = [e for e in events if e.event_type == "transcript_final"][0]
    assert transcript.data["detected_language"] == "hi"
    assert transcript.data["language"] == "gu"
    assert pipeline.forced_lang == "gu"
    assert pipeline.run_context.metadata["reply_language"] == "gu"


@pytest.mark.asyncio
async def test_stt_servicer_uses_request_language():
    import numpy as np

    from nexus.server.engines.base import STTEngine
    from nexus.server.services.base import HealthServicer
    from nexus.server.services.stt_server import SttServicer

    class _Engine(STTEngine):
        def __init__(self):
            self.last_lang = None

        @property
        def loaded(self) -> bool:
            return True

        def transcribe(self, audio, sample_rate, language):
            self.last_lang = language
            return "text"

    engine = _Engine()
    servicer = SttServicer(engine, HealthServicer("stt", "mock", ready=True))

    class _Req:
        pcm = (np.zeros(160, dtype=np.int16).tobytes())
        sample_rate = 16000
        language = "gu"

    resp = await servicer.Transcribe(_Req(), None)
    assert engine.last_lang == "gu"
    assert resp.language == "gu"
