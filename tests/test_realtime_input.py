"""Tests for multimodal input, realtime config, and vision context building."""

import base64

import pytest

from nexus.config.agent import AgentConfig
from nexus.config.llm import LLMProviderConfig
from nexus.realtime import (
    AudioPart,
    ImageBase64Part,
    RealtimeAgentConfig,
    STTConfig,
    TTSConfig,
    UserInput,
    VoiceTeamConfig,
)
from nexus.realtime.multimodal.context_builder import (
    VisionContextBuilder,
    content_parts_to_openai,
)
from nexus.session.models import AgentSession


def test_user_input_text_roundtrip():
    ui = UserInput.from_text("hello world")
    assert ui.to_text() == "hello world"
    assert not ui.has_images()
    assert not ui.has_audio()


def test_user_input_image_url():
    ui = UserInput.from_image_url("https://x/y.png", text="what is this?")
    assert ui.to_text() == "what is this?"
    assert ui.has_images()
    assert len(ui.image_parts()) == 1


def test_image_base64_data_url():
    part = ImageBase64Part.from_bytes(b"\x89PNG", mime_type="image/png")
    url = part.to_data_url()
    assert url.startswith("data:image/png;base64,")
    decoded = base64.b64decode(url.split(",", 1)[1])
    assert decoded == b"\x89PNG"


def test_audio_part_roundtrip():
    part = AudioPart.from_bytes(b"RIFFdata", mime_type="audio/wav", sample_rate=16000)
    assert part.to_bytes() == b"RIFFdata"
    ui = UserInput(parts=[part])
    assert ui.has_audio()
    assert ui.audio_parts()[0].sample_rate == 16000


def test_content_parts_to_openai_blocks():
    parts = [ImageBase64Part.from_bytes(b"img", mime_type="image/jpeg")]
    blocks = content_parts_to_openai("caption", parts)
    assert blocks[0] == {"type": "text", "text": "caption"}
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def _agent_config() -> AgentConfig:
    return AgentConfig(
        name="vision",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
    )


@pytest.mark.asyncio
async def test_vision_context_builder_attaches_image():
    builder = VisionContextBuilder()
    builder.pending_content_parts = [ImageBase64Part.from_bytes(b"img")]
    session = AgentSession(session_id="s1", agent_id="vision")
    messages = await builder.build(
        session=session,
        agent_config=_agent_config(),
        current_user_message="describe this",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs, "expected a user message"
    content = user_msgs[-1]["content"]
    assert isinstance(content, list)
    assert any(b["type"] == "image_url" for b in content)
    # Parts are consumed after one build.
    assert builder.pending_content_parts == []


@pytest.mark.asyncio
async def test_vision_context_builder_text_only_unchanged():
    builder = VisionContextBuilder()
    session = AgentSession(session_id="s2", agent_id="vision")
    messages = await builder.build(
        session=session,
        agent_config=_agent_config(),
        current_user_message="just text",
    )
    user_msgs = [m for m in messages if m["role"] == "user"]
    assert user_msgs[-1]["content"] == "just text"


def test_realtime_agent_config_defaults():
    cfg = RealtimeAgentConfig(name="ivr", agent=_agent_config())
    assert cfg.modality == "voice_cascaded"
    assert cfg.duplex == "full"
    assert cfg.is_voice
    assert isinstance(cfg.effective_stt(), STTConfig)
    assert isinstance(cfg.effective_tts(), TTSConfig)


def test_voice_team_config():
    responder = RealtimeAgentConfig(name="responder", agent=_agent_config())
    team = VoiceTeamConfig(name="team", responder=responder, context_agent=_agent_config())
    assert team.pattern == "voice_team"
    assert team.responder.name == "responder"
    assert team.context_agent is not None
