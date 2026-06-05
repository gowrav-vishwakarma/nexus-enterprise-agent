"""Tests for YAML-driven orchestration bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nexus.config.storage import SessionStorageConfig
from nexus.orchestration import (
    ManifestLoadError,
    OrchestrationManifest,
    OrchestrationRuntime,
    PromptNotFoundError,
    ReferenceCycleError,
)
from nexus.orchestration.env import interpolate_env
from nexus.orchestration.resolver import ManifestResolver
from nexus.persistence.factory import PersistenceBundle
from nexus.persistence.resolver import PersistenceResolver
from nexus.runner.agent_runner import AgentRunner
from nexus.multiagent.orchestrator import AgentOrchestrator
from nexus.config.agent import AgentConfig, AgentGroupConfig
from nexus.llm.response import LLMResponse, TokenUsage
from nexus.session.manager import SessionManager
from nexus.tools.context import RunContext
from nexus.tools.registry import ToolRegistry
from nexus.utils.jinja import render_system_prompt

FIXTURES = Path(__file__).parent / "fixtures" / "orchestration"


def test_env_interpolation_with_default():
    assert interpolate_env("${ENV:ORCH_MISSING_VAR|fallback}") == "fallback"


def test_env_interpolation_from_env(monkeypatch):
    monkeypatch.setenv("ORCH_TEST_ENV", "resolved")
    assert interpolate_env("${ENV:ORCH_TEST_ENV}") == "resolved"


def test_manifest_load_basic():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    assert manifest.schema.root == "research_pipeline"
    assert "researcher_system" in manifest.prompts
    assert manifest.storage_config.adapter == "memory"
    assert "fixture_search" in manifest.plugins


def test_manifest_missing_prompt_raises():
    manifest = OrchestrationManifest.load(FIXTURES / "missing_prompt.yaml")
    resolver = ManifestResolver(
        manifest.schema,
        manifest.prompts,
        RunContext(),
    )
    with pytest.raises(PromptNotFoundError):
        resolver.resolve_root()


def test_reference_cycle_detection():
    manifest = OrchestrationManifest.load(FIXTURES / "cycle.yaml")
    resolver = ManifestResolver(
        manifest.schema,
        manifest.prompts,
        RunContext(),
    )
    with pytest.raises(ReferenceCycleError) as exc:
        resolver.resolve_root()
    assert "loop_a" in exc.value.cycle_path


def test_unimplemented_pattern_warns_and_falls_back(caplog):
    manifest = OrchestrationManifest.load(FIXTURES / "parallel.yaml")
    resolver = ManifestResolver(
        manifest.schema,
        manifest.prompts,
        RunContext(),
    )
    with caplog.at_level(logging.WARNING):
        config = resolver.resolve_root()
    assert isinstance(config, AgentGroupConfig)
    assert config.pattern == "pipeline"
    assert any("falling back to pipeline" in record.message for record in caplog.records)


def test_nested_group_resolution():
    manifest = OrchestrationManifest.load(FIXTURES / "nested.yaml")
    resolver = ManifestResolver(
        manifest.schema,
        manifest.prompts,
        RunContext(tenant_id="tenant-1"),
    )
    config = resolver.resolve_root()
    assert isinstance(config, AgentGroupConfig)
    assert config.pattern == "supervisor"
    assert len(config.members) == 2
    nested = config.members[1]
    assert isinstance(nested, AgentGroupConfig)
    assert nested.pattern == "pipeline"


def test_prompt_template_and_callable_resolution():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    run_context = RunContext(tenant_id="tenant-42")
    resolver = ManifestResolver(
        manifest.schema,
        manifest.prompts,
        run_context,
    )
    config = resolver.resolve_root()
    assert isinstance(config, AgentGroupConfig)
    researcher = config.members[0]
    assert isinstance(researcher, AgentConfig)
    assert "{{ tenant_id }}" in researcher.persona.system_prompt_template
    assert "Tenant: tenant-42" not in researcher.persona.system_prompt_template
    analyst = config.members[1]
    assert isinstance(analyst, AgentConfig)
    assert "{{ tenant_id }}" in analyst.persona.system_prompt_template
    assert "Tenant=tenant-42" not in analyst.persona.system_prompt_template

    rendered = render_system_prompt(
        researcher.persona.model_dump(),
        run_context=run_context,
    )
    assert "Tenant: tenant-42" in rendered


class _OverrideResolver:
    def resolve_storage_config(
        self,
        tenant_id: str | None,
        user_id: str | None,
    ) -> SessionStorageConfig:
        return SessionStorageConfig(adapter="memory")

    def resolve_bundle(
        self,
        tenant_id: str | None,
        user_id: str | None,
    ) -> PersistenceBundle:
        manager = SessionManager()
        from nexus.memory.cross_session_store import InMemoryCrossSessionMemoryStore

        return PersistenceBundle(
            session_manager=manager,
            cross_session_memory_store=InMemoryCrossSessionMemoryStore(),
        )


def test_persistence_resolver_override():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(tenant_id="t1", session_id="sess-1"),
        persistence_resolver=_OverrideResolver(),
    )
    assert runtime.executor is not None


def test_tool_plugin_import_from_manifest():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(session_id="sess-tools"),
    )
    assert "fixture_search.search" in runtime.tool_registry._tools


def test_runtime_builds_orchestrator_with_member_session_prefix():
    manifest = OrchestrationManifest.load(FIXTURES / "nested.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(session_id="root-session", tenant_id="t1"),
    )
    assert isinstance(runtime.executor, AgentOrchestrator)
    orchestrator = runtime.executor
    supervisor_runner = orchestrator._members["supervisor"]
    assert isinstance(supervisor_runner, AgentRunner)
    assert supervisor_runner.run_context.session_id == "team_root-session_supervisor"


@pytest.mark.asyncio
async def test_runtime_integration_renders_tenant_in_system_prompt():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(tenant_id="tenant-integration", session_id="sess-int"),
    )
    orchestrator = runtime.executor
    assert isinstance(orchestrator, AgentOrchestrator)
    researcher = orchestrator._members["researcher"]
    assert isinstance(researcher, AgentRunner)

    response = LLMResponse(
        content="Done researching.",
        tool_calls=[],
        usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        finish_reason="stop",
        raw_response={},
    )
    mock_chat = AsyncMock(return_value=response)

    analyst = orchestrator._members["analyst"]
    assert isinstance(analyst, AgentRunner)

    with (
        patch.object(researcher.llm_proxy, "chat", mock_chat),
        patch.object(analyst.llm_proxy, "chat", mock_chat),
    ):
        result = await runtime.run("Analyze revenue", session_id="sess-int")

    assert result.final_response == "Done researching."
    assert mock_chat.await_count == 2
    researcher_messages = mock_chat.call_args_list[0].kwargs["messages"]
    system_message = researcher_messages[0]["content"]
    assert "Tenant: tenant-integration" in system_message


def test_single_agent_root():
    data = {
        "root": "solo",
        "agents": {
            "solo": {
                "llm": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "k"},
                "persona": {"role": "Solo", "goal": "Go"},
            }
        },
    }
    prompts = {"ignored": "unused"}
    manifest = OrchestrationManifest.from_dict(data, prompts=prompts)
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(session_id="solo-sess"),
    )
    assert isinstance(runtime.executor, AgentRunner)
    assert runtime.executor.config.name == "solo"


def test_prebuilt_tool_registry_is_not_replaced():
    manifest = OrchestrationManifest.load(FIXTURES / "basic.yaml")
    registry = ToolRegistry()
    runtime = OrchestrationRuntime.from_manifest(
        manifest,
        run_context=RunContext(session_id="sess-shared"),
        tool_registry=registry,
    )
    assert runtime.tool_registry is registry
    assert "fixture_search.search" in registry._tools
