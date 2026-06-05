"""Tests for S2S pipeline (tool bridge) and the VoiceTeam pattern."""

from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.config.agent import AgentConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.llm.response import LLMResponse, LLMStreamChunk, TokenUsage
from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.config import RealtimeAgentConfig, S2SConfig
from nexus.realtime.pipelines.speech_to_speech import SpeechToSpeechPipeline
from nexus.realtime.runtime import RealtimeRuntime, resolve_voice_team
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool, tool_plugin
from nexus.tools.registry import ToolRegistry

VOICE_TEAM_MANIFEST = (
    Path(__file__).parent.parent / "examples" / "orchestration" / "voice_team_support.yaml"
)


@tool_plugin(name="kb")
class _KBPlugin:
    @tool(name="lookup", description="Look up an order status by id")
    def lookup(self, order_id: str, run_context: RunContext) -> str:
        return f"Order {order_id}: shipped"


def _s2s_config(tool_plugins=None) -> RealtimeAgentConfig:
    agent = AgentConfig(
        name="s2s_agent",
        llm=LLMProviderConfig(provider="openai", model="gpt-4o", api_key="sk-test"),
        persona=AgentPersonaConfig(role="Voice Bot", goal="Help by voice"),
        tool_plugins=tool_plugins or [],
    )
    return RealtimeAgentConfig(
        name="s2s_agent",
        modality="voice_s2s",
        agent=agent,
        s2s=S2SConfig(provider="mock"),
    )


@pytest.mark.asyncio
async def test_s2s_pipeline_echo():
    pipeline = SpeechToSpeechPipeline(_s2s_config(), run_context=RunContext())
    events = [ev async for ev in pipeline.process_text("hello")]
    finals = [e for e in events if e.event_type == "final_response"]
    assert finals[0].content == "echo: hello"
    assert any(e.event_type == "audio_out" for e in events)


@pytest.mark.asyncio
async def test_s2s_tool_bridge_executes_registry_tool():
    registry = ToolRegistry()
    registry.register_plugin(_KBPlugin())
    pipeline = SpeechToSpeechPipeline(
        _s2s_config(tool_plugins=["kb"]),
        tool_registry=registry,
        run_context=RunContext(),
    )
    # Tool schemas should be exposed with realtime-safe names.
    assert "kb-lookup" in pipeline._name_map
    assert pipeline._name_map["kb-lookup"] == ("kb", "lookup")

    events = [
        ev
        async for ev in pipeline.process_text('TOOL:kb-lookup {"order_id": "A1"}')
    ]
    tool_results = [e for e in events if e.event_type == "tool_result"]
    assert tool_results[0].content == "Order A1: shipped"
    final = [e for e in events if e.event_type == "final_response"][0]
    assert "shipped" in final.content


def test_resolve_voice_team_from_manifest():
    manifest = OrchestrationManifest.load(VOICE_TEAM_MANIFEST)
    rc = RunContext(tenant_id="t", user_id="u", session_id="s")
    team = resolve_voice_team("support_team", manifest, rc)
    assert team.responder.name == "responder"
    assert team.responder.modality == "voice_cascaded"
    assert team.context_agent is not None
    assert team.context_injection_var == "live_context"


@pytest.mark.asyncio
async def test_voice_team_injects_context():
    manifest = OrchestrationManifest.load(VOICE_TEAM_MANIFEST)
    rc = RunContext(tenant_id="t", user_id="u", session_id="s")
    runtime = RealtimeRuntime.from_manifest(manifest, run_context=rc)
    team = runtime.build_voice_team("support_team")

    seen_messages = []

    def chat_stream_for(reply: str):
        async def chat_stream(messages=None, *a, **k):
            seen_messages.append(messages)

            async def gen():
                yield LLMStreamChunk(content=reply)
                yield LLMStreamChunk(content=None, finish_reason="stop", usage=TokenUsage())
            return gen()

        return chat_stream

    async def context_chat(messages=None, *a, **k):
        return LLMResponse(content="- Order shipped", finish_reason="stop", usage=TokenUsage())

    with patch.object(
        team.context_runner.llm_proxy, "chat", context_chat
    ), patch.object(
        team.responder.runner.llm_proxy, "chat_stream", chat_stream_for("Your order shipped.")
    ):
        events = [ev async for ev in team.process_text("where is my order", session_id="s")]

    # Team emits the raw user transcript, the context event, and the spoken reply.
    transcripts = [e for e in events if e.event_type == "transcript_final"]
    assert transcripts[0].content == "where is my order"
    ctx_events = [e for e in events if e.data and "context_agent" in (e.data or {})]
    assert ctx_events and "shipped" in ctx_events[0].data["context_agent"]
    final = [e for e in events if e.event_type == "final_response"][0]
    assert final.content == "Your order shipped."

    # The responder must have received the injected context in its prompt.
    responder_msgs = seen_messages[-1]
    joined = " ".join(m.get("content", "") for m in responder_msgs if isinstance(m.get("content"), str))
    assert "live_context" in joined
