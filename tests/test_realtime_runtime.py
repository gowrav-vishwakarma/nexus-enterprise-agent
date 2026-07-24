"""Tests for RealtimeRuntime manifest resolution and pipeline building."""

from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.llm.response import LLMStreamChunk, TokenUsage
from nexus.orchestration.manifest import OrchestrationManifest
from nexus.realtime.pipelines.cascaded import CascadedVoicePipeline
from nexus.realtime.runtime import RealtimeRuntime, resolve_realtime_agent
from nexus.realtime.tools.ivr import IVRMenuPlugin
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry

IVR_MANIFEST = Path(__file__).parent.parent / "examples" / "orchestration" / "ivr_support.yaml"


def _run_context() -> RunContext:
    return RunContext(tenant_id="t1", user_id="+1555", session_id="call-1")


def _build_ivr_registry() -> ToolRegistry:
    """Build a registry with the IVR plugin tools exposed as a toolset."""
    registry = ToolRegistry()
    registry.register_plugin(IVRMenuPlugin())
    ivr_tools = [name for name in registry.tool_names() if name.startswith("ivr_menu.")]
    registry.add_toolset("ivr_menu", ivr_tools)
    return registry


def test_resolve_realtime_agent_from_manifest():
    manifest = OrchestrationManifest.load(IVR_MANIFEST)
    rt = resolve_realtime_agent("ivr_support", manifest, _run_context())
    assert rt.modality == "voice_cascaded"
    assert rt.duplex == "half"
    assert rt.agent.name == "ivr_support"
    # Modern path: the manifest selects the IVR toolset instead of using tool_plugins.
    assert rt.agent.toolset == "ivr_menu"
    assert rt.stt is not None and rt.stt.provider == "mock"
    assert rt.tts is not None and rt.tts.provider == "mock"


@pytest.mark.asyncio
async def test_runtime_builds_pipeline_and_runs():
    manifest = OrchestrationManifest.load(IVR_MANIFEST)
    registry = _build_ivr_registry()
    runtime = RealtimeRuntime.from_manifest(
        manifest, run_context=_run_context(), tool_registry=registry
    )
    pipeline = runtime.build_pipeline("ivr_support")
    assert isinstance(pipeline, CascadedVoicePipeline)

    async def chat_stream(*args, **kwargs):
        async def gen():
            yield LLMStreamChunk(content="Press 2 for billing.")
            yield LLMStreamChunk(
                content=None,
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=4, completion_tokens=2, total_tokens=6),
            )
        return gen()

    with patch.object(pipeline.runner.llm_proxy, "chat_stream", chat_stream):
        events = [ev async for ev in pipeline.process_text("billing", session_id="call-1")]

    finals = [e for e in events if e.event_type == "final_response"]
    assert finals and finals[0].content == "Press 2 for billing."
    # The ivr_menu toolset should resolve to the plugin's tools on the registry.
    resolved_tools = registry.resolve_toolset("ivr_menu")
    assert any(name.startswith("ivr_menu.") for name in resolved_tools)
