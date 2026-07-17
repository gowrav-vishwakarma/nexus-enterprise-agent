"""Tests for connect-time initial_response and language metadata seeding."""

from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.config import (
    InitialResponseConfig,
    LanguageConfig,
    RealtimeAgentConfig,
    STTConfig,
)
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.realtime.session import RealtimeSession
from nexus.realtime.transport.memory import InMemoryTransport
from nexus.realtime.validation import validate_voice_languages_static
from nexus.session.manager import SessionManager


def _rt_config(
    *,
    initial_response: InitialResponseConfig | None = None,
    languages: LanguageConfig | None = None,
    duplex: str = "full",
    tool_plugins: list[str] | None = None,
) -> RealtimeAgentConfig:
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
        stt=STTConfig(provider="mock", language="hi"),
        languages=languages or LanguageConfig(allowed=["hi", "en"], default="hi"),
        initial_response=initial_response,
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
async def test_proactive_direct_tts_no_llm():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(
            mode="proactive",
            text="Namaste!",
            via_llm=False,
        ),
    )
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    events = [ev async for ev in pipeline.run_initial_response(session_id="s1")]
    audio = [e for e in events if e.event_type == "audio_out"]
    assert len(audio) == 1
    assert b"Namaste!" in audio[0].audio


@pytest.mark.asyncio
async def test_proactive_via_llm():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(
            mode="proactive",
            via_llm=True,
            llm_trigger="Greet the caller.",
        ),
    )
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    with patch.object(pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Hello there."])):
        events = [ev async for ev in pipeline.run_initial_response(session_id="s2")]
    assert any(e.event_type == "audio_out" for e in events)
    assert any(e.event_type == "final_response" for e in events)


@pytest.mark.asyncio
async def test_ivr_script_multiple_chunks():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(
            mode="ivr",
            via_llm=False,
            ivr_script=["Welcome.", "Press 1 for sales."],
        ),
        duplex="half",
    )
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    events = [ev async for ev in pipeline.run_initial_response(session_id="s3")]
    audio = [e for e in events if e.event_type == "audio_out"]
    assert len(audio) == 2


@pytest.mark.asyncio
async def test_ivr_via_llm():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(mode="ivr", via_llm=True),
        duplex="half",
        tool_plugins=["ivr_menu"],
    )
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    with patch.object(pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Main menu."])):
        events = [ev async for ev in pipeline.run_initial_response(session_id="s4")]
    assert any(e.event_type == "final_response" for e in events)


def test_seed_language_metadata():
    cfg = _rt_config(languages=LanguageConfig(allowed=["hi", "en"], default="hi"))
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    pipeline.seed_language_metadata()
    assert pipeline.run_context.metadata["reply_language"] == "hi"
    assert pipeline.run_context.metadata["allowed_languages"] == ["en", "hi"]


@pytest.mark.asyncio
async def test_session_runs_initial_response_on_full_duplex_connect():
    """Full duplex: greeting runs concurrently with the audio loop (interruptible)."""
    cfg = _rt_config(
        initial_response=InitialResponseConfig(
            mode="proactive",
            text="Hi!",
            via_llm=False,
        ),
    )
    pipeline = CascadedVoicePipeline(cfg, storage_config=SessionManager(), tts=MockTTS())
    transport = InMemoryTransport()
    session = RealtimeSession(pipeline, transport, session_id="s5")
    await transport.end_input()
    await session.run_audio()
    assert transport.sent_audio
    assert any(e.event_type == "audio_out" for e in transport.sent_events)


def test_validation_proactive_missing_text():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(mode="proactive", via_llm=False),
    )
    issues = validate_voice_languages_static(cfg)
    assert any(i.code == "initial_response_missing_text" for i in issues)


def test_validation_ivr_warnings():
    cfg = _rt_config(
        initial_response=InitialResponseConfig(mode="ivr", via_llm=True),
        duplex="full",
    )
    issues = validate_voice_languages_static(cfg)
    codes = {i.code for i in issues}
    assert "initial_response_ivr_not_half_duplex" in codes
    assert "initial_response_ivr_no_plugin" in codes
