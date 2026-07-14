"""Tests for voice agent language config and startup validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.realtime.adapters.lid.base import LIDResult
from nexus.realtime.adapters.lid.mock import MockLID
from nexus.realtime.adapters.stt.mock import MockSTT
from nexus.realtime.adapters.tts.mock import MockTTS
from nexus.realtime.config import (
    LanguageConfig,
    LIDConfig,
    RealtimeAgentConfig,
    STTConfig,
    TTSConfig,
)
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.realtime.validation import (
    LanguageValidationIssue,
    validate_voice_languages,
    validate_voice_languages_static,
    log_validation_issues,
)
from nexus.server.config import ModelServerSpec
from nexus.session.manager import SessionManager



def _mock_chat_stream(text_chunks):
    from nexus.llm.response import LLMStreamChunk, TokenUsage

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


def _servers(**specs: dict) -> dict[str, ModelServerSpec]:
    return {name: ModelServerSpec(**data) for name, data in specs.items()}


def _rt_config(
    *,
    languages: LanguageConfig | None = None,
    lid: LIDConfig | None = None,
    stt: STTConfig | None = None,
    tts: TTSConfig | None = None,
) -> RealtimeAgentConfig:
    agent = AgentConfig(
        name="voice_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o-mini", api_key="sk-test"),
    )
    return RealtimeAgentConfig(
        name="voice_agent",
        modality="voice_cascaded",
        duplex="full",
        agent=agent,
        stt=stt or STTConfig(provider="nexus_server", server_ref="indic_stt", language="hi"),
        tts=tts or TTSConfig(provider="nexus_server", server_ref="indic_tts"),
        lid=lid,
        languages=languages,
    )


def test_en_allowed_without_lid_warns():
    cfg = _rt_config(
        languages=LanguageConfig(allowed=["hi", "en"], default="hi"),
        lid=None,
    )
    issues = validate_voice_languages_static(
        cfg,
        servers=_servers(indic_stt={"kind": "stt", "engine": "conformer", "port": 50051}),
    )
    codes = {i.code for i in issues}
    assert "en_requires_lid" in codes


def test_unknown_language_is_error():
    cfg = _rt_config(languages=LanguageConfig(allowed=["xx"], default="xx"))
    issues = validate_voice_languages_static(cfg)
    assert any(i.severity == "error" and i.code == "unknown_language" for i in issues)


def test_indic_allowed_subset_passes_conformer():
    cfg = _rt_config(
        languages=LanguageConfig(allowed=["hi", "gu", "ta"], default="hi"),
        lid=LIDConfig(provider="nexus_server", server_ref="whisper_lid"),
    )
    servers = _servers(
        indic_stt={"kind": "stt", "engine": "conformer", "port": 50051},
        indic_tts={"kind": "tts", "engine": "parler", "port": 50052},
        whisper_lid={"kind": "lid", "engine": "faster_whisper", "port": 50054},
    )
    issues = validate_voice_languages_static(cfg, servers=servers)
    assert not any(i.severity == "error" for i in issues)
    assert not any(i.code == "stt_lang_unsupported" for i in issues)


def test_ta_allowed_mock_stt_warns():
    cfg = _rt_config(
        languages=LanguageConfig(allowed=["hi", "ta"], default="hi"),
        stt=STTConfig(provider="nexus_server", server_ref="mock_stt", language="hi"),
    )
    servers = _servers(mock_stt={"kind": "stt", "engine": "mock", "port": 50051})
    issues = validate_voice_languages_static(cfg, servers=servers)
    assert any(i.code == "stt_lang_unsupported" and "ta" in i.message for i in issues)


@pytest.mark.asyncio
async def test_live_meta_validation():
    cfg = _rt_config(
        languages=LanguageConfig(allowed=["hi", "ta"], default="hi"),
        stt=STTConfig(provider="nexus_server", server_ref="mock_stt", language="hi"),
    )
    servers = _servers(mock_stt={"kind": "stt", "engine": "mock", "port": 50051})
    registry = MagicMock()
    meta = MagicMock()
    meta.languages = ["en", "hi"]
    registry.fetch_meta = AsyncMock(return_value=meta)
    issues = await validate_voice_languages(cfg, servers=servers, server_registry=registry)
    assert any(i.code == "stt_lang_unsupported_live" for i in issues)


@pytest.mark.asyncio
async def test_pipeline_clamps_out_of_allowed_detection():
    lid = MockLID(LIDConfig(provider="mock"))
    lid.detect = AsyncMock(return_value=LIDResult(language="ta", confidence=1.0))
    stt = MockSTT()
    stt.transcribe = AsyncMock(return_value="hello")

    cfg = _rt_config(
        languages=LanguageConfig(allowed=["hi", "en"], default="hi"),
        lid=LIDConfig(provider="mock"),
    )
    pipeline = CascadedVoicePipeline(
        cfg,
        storage_config=SessionManager(),
        stt=stt,
        tts=MockTTS(),
        lid=lid,
    )
    with patch.object(pipeline.runner.llm_proxy, "chat_stream", _mock_chat_stream(["Ok."])):
        async for _ev in pipeline.process_utterance(b"audio"):
            pass

    assert pipeline.session_lang == "hi"
    assert pipeline.run_context.metadata["reply_language"] == "hi"


def test_missing_server_ref_is_error():
    cfg = _rt_config(
        stt=STTConfig(provider="nexus_server", server_ref=None, language="hi"),
    )
    issues = validate_voice_languages_static(cfg)
    assert any(i.code == "stt_missing_server_ref" for i in issues)


def test_strict_mode_raises(monkeypatch):
    monkeypatch.setenv("NEXUS_VOICE_STRICT_LANG", "1")
    issues = [
        LanguageValidationIssue("error", "unknown_language", "bad code"),
    ]
    with pytest.raises(RuntimeError, match="Voice language validation failed"):
        log_validation_issues(issues)
