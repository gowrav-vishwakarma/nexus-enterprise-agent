"""S2S provider routing for Moshi-family servers (Moshi + Human-1)."""

import pytest

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.realtime.config import RealtimeAgentConfig, S2SConfig
from nexus.realtime.adapters.s2s.mock import MockS2S
from nexus.realtime.pipelines.speech_to_speech import SpeechToSpeechPipeline


def _pipeline(provider: str) -> SpeechToSpeechPipeline:
    agent = AgentConfig(
        name="s2s",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
        persona=AgentPersonaConfig(role="Voice", goal="Talk"),
    )
    rt = RealtimeAgentConfig(
        name="s2s",
        modality="voice_s2s",
        agent=agent,
        s2s=S2SConfig(provider=provider, base_url="ws://localhost:8998"),
    )
    return SpeechToSpeechPipeline(rt)


@pytest.mark.parametrize("provider", ["moshi", "human-1", "human1"])
def test_human1_uses_moshi_adapter(provider: str):
    from nexus.realtime.adapters.s2s.moshi import MoshiS2S

    pipe = _pipeline(provider)
    adapter = pipe._build_adapter([])
    assert isinstance(adapter, MoshiS2S)
    assert adapter._provider == provider.lower()


def test_unknown_s2s_provider_raises():
    agent = AgentConfig(
        name="s2s",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
        persona=AgentPersonaConfig(role="Voice", goal="Talk"),
    )
    rt = RealtimeAgentConfig(
        name="s2s",
        modality="voice_s2s",
        agent=agent,
        s2s=S2SConfig(provider="unknown_xyz"),
    )
    pipe = SpeechToSpeechPipeline(rt, adapter=MockS2S(rt.s2s))
    with pytest.raises(ValueError, match="Unknown S2S provider"):
        pipe._build_adapter([])
