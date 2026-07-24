"""Live-LLM multi-agent orchestration smoke tests.

These tests make real LLM calls and are skipped by default. Run with:

    uv run pytest -m live_llm tests/test_orchestration_live_llm.py

The tests read the LiteLLM proxy credentials from the repo `.env` via
NEXUS_LLM_*. They are intentionally small (one pipeline + one supervisor team)
to keep API cost low.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from nexus.config.agent import AgentConfig, AgentGroupConfig, AgentPersonaConfig
from nexus.config.llm import LLMProviderConfig
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.orchestration import OrchestrationManifest, OrchestrationRuntime
from nexus.runner.agent_runner import AgentRunner
from nexus.tools.context import RunContext
from nexus.tools.decorators import tool
from nexus.tools.registry import ToolRegistry


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def llm_config_from_env() -> LLMProviderConfig:
    """Build LLM config from NEXUS_LLM_* or PLATFORM_OPENAI_KEY env vars."""
    _load_env()
    provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")
    base_url = os.getenv("NEXUS_LLM_BASE_URL", "") or None
    model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
    api_key = os.getenv("NEXUS_LLM_API_KEY") or os.getenv("PLATFORM_OPENAI_KEY", "")
    if not api_key or api_key.startswith("sk-your-"):
        pytest.skip("No LLM API key configured (set NEXUS_LLM_API_KEY or PLATFORM_OPENAI_KEY)")
    return LLMProviderConfig(
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
    )


@tool(name="search_web", description="Search the web for a short query.")
def search_web(query: str) -> str:
    return f"[web result for {query}]"


@tool(name="analyze_data", description="Analyze a block of data and return a concise summary.")
def analyze_data(data: str) -> str:
    return f"[analysis of {len(data)} chars]"


@tool(name="format_report", description="Format a final report from a summary.")
def format_report(summary: str) -> str:
    return f"[formatted report: {summary}]"


def build_test_registry() -> ToolRegistry:
    """Registry with three flat tools grouped into researcher/analyst/writer packs."""
    registry = ToolRegistry()
    registry.add_toolset("researcher", [search_web])
    registry.add_toolset("analyst", [analyze_data])
    registry.add_toolset("writer", [format_report])
    registry.add_toolset("full_team", includes=["researcher", "analyst", "writer"])
    return registry


def _agent(name: str, role: str, goal: str, toolset: str | None) -> AgentConfig:
    return AgentConfig(
        name=name,
        llm=llm_config_from_env(),
        persona=AgentPersonaConfig(role=role, goal=goal),
        toolset=toolset,
    )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_pipeline_team_with_toolsets() -> None:
    """A two-agent pipeline: researcher -> analyst, both using registry toolsets."""
    registry = build_test_registry()

    group = AgentGroupConfig(
        name="research_pipeline",
        pattern="pipeline",
        members=[
            _agent("researcher", "Researcher", "Find facts", "researcher"),
            _agent("analyst", "Analyst", "Summarize findings", "analyst"),
        ],
    )

    orchestrator = AgentOrchestrator(
        config=group,
        tool_registry=registry,
        run_context=RunContext(tenant_id="demo", user_id="demo", session_id="live-pipeline-1"),
    )

    result = await orchestrator.run("What are the key benefits of using named toolsets?")
    assert result.final_response
    assert len(result.final_response) > 10


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_supervisor_team_with_toolsets() -> None:
    """A supervisor delegates to a researcher and an analyst toolset."""
    registry = build_test_registry()

    group = AgentGroupConfig(
        name="research_team",
        pattern="supervisor",
        members=[
            _agent("supervisor", "Supervisor", "Coordinate the team", "full_team"),
            _agent("researcher", "Researcher", "Find facts", "researcher"),
            _agent("analyst", "Analyst", "Summarize findings", "analyst"),
        ],
    )

    orchestrator = AgentOrchestrator(
        config=group,
        tool_registry=registry,
        run_context=RunContext(tenant_id="demo", user_id="demo", session_id="live-supervisor-1"),
    )

    result = await orchestrator.run("Explain the difference between toolset and tool_plugins.")
    assert result.final_response
    assert len(result.final_response) > 10


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_manifest_runtime_with_prebuilt_registry() -> None:
    """OrchestrationRuntime loads a manifest and uses a pre-built ToolRegistry."""
    registry = build_test_registry()
    registry.add_toolset("demo", includes=["researcher", "analyst"])

    # Inline manifest to avoid coupling to the example YAML and its plugins.
    manifest = OrchestrationManifest.from_dict(
        {
            "version": "1",
            "root": "demo_team",
            "agents": {
                "researcher": {
                    "llm": llm_config_from_env().model_dump(),
                    "toolset": "researcher",
                    "persona": {"role": "Researcher", "goal": "Find facts"},
                },
                "analyst": {
                    "llm": llm_config_from_env().model_dump(),
                    "toolset": "analyst",
                    "persona": {"role": "Analyst", "goal": "Summarize findings"},
                },
            },
            "groups": {
                "demo_team": {
                    "pattern": "pipeline",
                    "members": ["researcher", "analyst"],
                }
            },
        }
    )

    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(
            tenant_id="demo", user_id="demo", session_id="live-manifest-1"
        ),
        tool_registry=registry,
    )

    result = await runtime.run("Why is a ToolRegistry useful for multi-agent apps?")
    assert result.final_response
    assert len(result.final_response) > 10


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_toolset_allow_list_restricts_schemas() -> None:
    """An agent with a toolset only sees the tools in that pack."""
    registry = build_test_registry()
    config = AgentConfig(
        name="researcher",
        llm=llm_config_from_env(),
        persona=AgentPersonaConfig(role="Researcher", goal="Find facts"),
        toolset="researcher",
    )

    runner = AgentRunner(
        config=config,
        tool_registry=registry,
        run_context=RunContext(tenant_id="demo", user_id="demo", session_id="live-allowlist-1"),
    )

    # Runner should only expose search_web to the model.
    runner._resolve_toolsets()
    assert runner._allowed_tools is not None
    assert runner._allowed_tools == {"search_web"}
